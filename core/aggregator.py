"""Aggregator module for combining listings from multiple scrapers."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.models import Property
from core.database import Database
from core.filter import PropertyFilter


class PropertyAggregator:
    """Aggregates property listings from multiple scrapers and processes them."""

    def __init__(self, config: dict, database: Database):
        self.config = config
        self.database = database
        self.logger = logging.getLogger(self.__class__.__name__)

        # Initialize scrapers based on config
        self.scrapers = []
        scraper_config = config.get("scrapers", {})

        if scraper_config.get("rightmove", {}).get("enabled", False):
            try:
                from scrapers.rightmove_scraper import RightmoveScraper
                rm_config = {**scraper_config.get("rightmove", {}), **self._search_params()}
                self.scrapers.append(RightmoveScraper(rm_config))
                self.logger.info("Rightmove scraper enabled")
            except Exception as e:
                self.logger.error(f"Failed to init Rightmove scraper: {e}")

        if scraper_config.get("zoopla", {}).get("enabled", False):
            try:
                from scrapers.zoopla_scraper import ZooplaScraper
                zp_config = {**scraper_config.get("zoopla", {}), **self._search_params()}
                self.scrapers.append(ZooplaScraper(zp_config))
                self.logger.info("Zoopla scraper enabled")
            except Exception as e:
                self.logger.error(f"Failed to init Zoopla scraper: {e}")

        if scraper_config.get("onthemarket", {}).get("enabled", False):
            try:
                from scrapers.onthemarket_scraper import OnTheMarketScraper
                otm_config = {**scraper_config.get("onthemarket", {}), **self._search_params()}
                self.scrapers.append(OnTheMarketScraper(otm_config))
                self.logger.info("OnTheMarket scraper enabled")
            except Exception as e:
                self.logger.error(f"Failed to init OnTheMarket scraper: {e}")

        if not self.scrapers:
            self.logger.warning("No scrapers enabled!")

        # Initialize filter
        self.property_filter = PropertyFilter(config)

    def _search_params(self) -> dict:
        """Extract search parameters from config for scraper-level filtering."""
        search = self.config.get("search", {})
        return {
            "price_min": search.get("price_min", 0),
            "price_max": search.get("price_max", 1000000),
            "bedrooms_min": search.get("bedrooms_min", 1),
            "bedrooms_max": search.get("bedrooms_max", 4),
        }

    def fetch_all(self) -> list[Property]:
        """Fetch listings from all scrapers for all areas concurrently."""
        areas = self.config.get("areas", [])
        if not areas:
            self.logger.warning("No areas configured")
            return []

        all_properties: list[Property] = []

        with ThreadPoolExecutor(max_workers=len(self.scrapers)) as executor:
            futures = {}
            for scraper in self.scrapers:
                for area in areas:
                    future = executor.submit(self._safe_fetch, scraper, area)
                    futures[future] = f"{scraper.name}:{area.get('name', '?')}"

            for future in as_completed(futures):
                label = futures[future]
                try:
                    props = future.result(timeout=120)
                    self.logger.info(f"{label}: found {len(props)} listings")
                    all_properties.extend(props)
                except TimeoutError:
                    self.logger.error(f"{label}: timed out")
                except Exception as e:
                    self.logger.error(f"{label} failed: {e}")

        # Deduplicate by URL
        seen_urls = set()
        unique = []
        for prop in all_properties:
            if prop.url and prop.url not in seen_urls:
                seen_urls.add(prop.url)
                unique.append(prop)
            elif not prop.url:
                unique.append(prop)

        self.logger.info(
            f"Total: {len(all_properties)} fetched, {len(unique)} unique "
            f"from {len(self.scrapers)} sources"
        )
        return unique

    def _safe_fetch(self, scraper, area_config: dict) -> list[Property]:
        """Safely fetch listings from a scraper."""
        try:
            return scraper.fetch_listings(area_config)
        except Exception as e:
            self.logger.error(f"Error in {scraper.name} for {area_config.get('name')}: {e}")
            return []

    def process_new_listings(self) -> tuple[list[Property], list[Property]]:
        """Fetch, filter, and return (all_new, hot_listings)."""
        all_listings = self.fetch_all()

        new_listings: list[Property] = []
        hot_listings: list[Property] = []
        new_count = 0
        filtered_count = 0

        for prop in all_listings:
            try:
                prop_dict = prop.to_dict()

                if self.database.add_property(prop_dict):
                    new_count += 1

                    passed, reason = self.property_filter.passes(prop)
                    if passed:
                        new_listings.append(prop)
                        if self.property_filter.is_hot(prop):
                            hot_listings.append(prop)
                    else:
                        filtered_count += 1
                        self.logger.debug(f"Filtered: {prop.title[:50]}... ({reason})")

            except Exception as e:
                self.logger.error(f"Error processing {prop.id}: {e}")

        self.logger.info(
            f"Summary: {len(all_listings)} fetched, {new_count} new, "
            f"{len(new_listings)} passed filters, {filtered_count} filtered out, "
            f"{len(hot_listings)} hot listings"
        )
        return new_listings, hot_listings

    def get_stats(self) -> dict:
        try:
            db_stats = self.database.get_stats()
        except Exception as e:
            self.logger.error(f"Error getting stats: {e}")
            db_stats = {}

        return {
            "scrapers": {
                "enabled": [s.name for s in self.scrapers],
                "count": len(self.scrapers),
            },
            "database": db_stats,
        }
