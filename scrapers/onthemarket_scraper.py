"""Scraper for OnTheMarket.com property listings."""

import json
import logging
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from core.models import Property
from scrapers.base_scraper import BaseScraper


class OnTheMarketScraper(BaseScraper):
    """Scraper for OnTheMarket using standard requests."""

    BASE_URL = "https://www.onthemarket.com"

    @property
    def name(self) -> str:
        return "onthemarket"

    def __init__(self, config: dict):
        super().__init__(config)
        self.session = requests.Session()
        self.session.headers.update(self.get_headers())

    def fetch_listings(self, area_config: dict) -> list[Property]:
        """Fetch listings for a specific area from OnTheMarket."""
        properties = []
        outcode = area_config.get("onthemarket_outcode", "")
        if not outcode:
            self.logger.warning(f"No OnTheMarket outcode for area: {area_config.get('name')}")
            return properties

        for page_num in range(1, 4):  # Pages 1-3
            try:
                page_props = self._fetch_page(outcode, page_num)
                properties.extend(page_props)

                if len(page_props) == 0:
                    break

                if page_num < 3:
                    self._rate_limit()
            except Exception as e:
                self.logger.error(f"Error fetching OnTheMarket page {page_num}: {e}")
                break

        self.logger.info(
            f"Fetched {len(properties)} listings from OnTheMarket "
            f"for {area_config.get('name', outcode)}"
        )
        return properties

    def _fetch_page(self, outcode: str, page: int) -> list[Property]:
        """Fetch a single page of OnTheMarket results."""
        url = self._build_search_url(outcode, page)
        self.logger.debug(f"Fetching: {url}")

        response = self.session.get(url, timeout=30)
        self._request_count += 1

        if response.status_code == 403:
            self.logger.warning("OnTheMarket returned 403 - possible block")
            return []

        response.raise_for_status()
        return self._extract_listings(response.text)

    def _build_search_url(self, outcode: str, page: int = 1) -> str:
        """Build OnTheMarket search URL with filters."""
        price_min = self.config.get("price_min", 0)
        price_max = self.config.get("price_max", 1000000)
        beds_min = self.config.get("bedrooms_min", 1)

        params = [
            f"min-price={price_min}",
            f"max-price={price_max}",
            f"min-bedrooms={beds_min}",
            "property-type=flat",
            "retirement=false",
            "shared-ownership=false",
            "sort-field=price",
        ]
        if page > 1:
            params.append(f"page={page}")

        return f"{self.BASE_URL}/for-sale/flats/{outcode.lower()}/?{'&'.join(params)}"

    def _extract_listings(self, html: str) -> list[Property]:
        """Extract listings from OnTheMarket HTML page."""
        properties = []
        soup = BeautifulSoup(html, "lxml")

        # Try __NEXT_DATA__ first (OnTheMarket may use Next.js)
        next_data = soup.find("script", id="__NEXT_DATA__")
        if next_data and next_data.string:
            try:
                data = json.loads(next_data.string)
                props = data.get("props", {}).get("pageProps", {})
                listings = (
                    props.get("properties", [])
                    or props.get("listings", [])
                    or props.get("results", [])
                    or []
                )
                for item in listings:
                    prop = self._parse_json_property(item)
                    if prop:
                        properties.append(prop)
                if properties:
                    return properties
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                self.logger.debug(f"Error parsing __NEXT_DATA__: {e}")

        # Try embedded JSON in script tags
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if self._looks_like_property(item):
                            prop = self._parse_jsonld_property(item)
                            if prop:
                                properties.append(prop)
                elif self._looks_like_property(data):
                    prop = self._parse_jsonld_property(data)
                    if prop:
                        properties.append(prop)
            except (json.JSONDecodeError, TypeError):
                pass

        if properties:
            return properties

        # Fallback: HTML card parsing
        properties = self._parse_html_listings(soup)
        return properties

    def _looks_like_property(self, data: dict) -> bool:
        """Heuristic check if a JSON object is a property listing."""
        if not isinstance(data, dict):
            return False
        return any(k in data for k in ("price", "bedrooms", "address", "numberOfRooms"))

    def _parse_json_property(self, data: dict) -> Optional[Property]:
        """Parse a property from OnTheMarket JSON data."""
        try:
            if not isinstance(data, dict):
                return None

            prop_id = str(
                data.get("id", "")
                or data.get("property-id", "")
                or data.get("propertyId", "")
                or ""
            )
            if not prop_id:
                return None

            # Price
            price = 0
            price_data = data.get("price", {})
            if isinstance(price_data, dict):
                price = price_data.get("amount", 0) or price_data.get("value", 0)
                if not price:
                    price = self._normalize_price(price_data.get("display", ""))
            elif isinstance(price_data, (int, float)):
                price = int(price_data)
            elif isinstance(price_data, str):
                price = self._normalize_price(price_data)

            # Address
            address_data = data.get("address", "")
            if isinstance(address_data, dict):
                address = address_data.get("display", "") or ", ".join(
                    filter(None, [
                        address_data.get("line1", ""),
                        address_data.get("line2", ""),
                        address_data.get("town", ""),
                        address_data.get("postcode", ""),
                    ])
                )
            else:
                address = str(address_data)

            postcode = self._extract_postcode(address)
            area = self._extract_postcode_district(postcode or address)

            # Beds/baths
            bedrooms = data.get("bedrooms", 0) or data.get("beds", 0)
            bathrooms = data.get("bathrooms", 0) or data.get("baths", 0)
            if isinstance(bedrooms, str):
                bedrooms = int(bedrooms) if bedrooms.isdigit() else 0
            if isinstance(bathrooms, str):
                bathrooms = int(bathrooms) if bathrooms.isdigit() else 0

            # URL
            url = data.get("url", "") or data.get("detailUrl", "")
            if url and not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"
            if not url:
                url = f"{self.BASE_URL}/details/{prop_id}"

            # Images
            image_url = ""
            images = data.get("images", []) or data.get("media", {}).get("images", [])
            if isinstance(images, list) and images:
                first = images[0]
                image_url = first.get("url", "") or first.get("src", "") if isinstance(first, dict) else str(first)

            # Floorplans
            floorplan_urls = []
            floorplans = data.get("floorplans", []) or data.get("floorPlanImages", [])
            for fp in floorplans:
                fp_url = fp.get("url", "") or fp.get("src", "") if isinstance(fp, dict) else str(fp)
                if fp_url:
                    floorplan_urls.append(fp_url)

            # Description
            description = data.get("description", "") or data.get("summary", "")
            features_detected = self._detect_features(description)

            # Property type
            property_type = data.get("propertyType", "") or data.get("property_type", "")

            # Location
            lat = float(data.get("latitude", 0) or data.get("lat", 0) or 0)
            lon = float(data.get("longitude", 0) or data.get("lng", 0) or data.get("lon", 0) or 0)

            # EPC
            epc = data.get("epcRating", "") or self._extract_epc(description)

            # Tenure
            tenure = data.get("tenure", "") or ""

            # Agent
            agent_data = data.get("agent", {}) or data.get("branch", {})
            agent_name = agent_data.get("name", "") if isinstance(agent_data, dict) else ""
            agent_phone = agent_data.get("phone", "") if isinstance(agent_data, dict) else ""

            # sqm
            sqm, sqm_source = self._extract_sqm_from_text(description)

            return Property(
                id=Property.generate_id("onthemarket", prop_id),
                source="onthemarket",
                title=data.get("title", "") or f"{bedrooms} bed {property_type} - {address}",
                price=int(price) if price else 0,
                bedrooms=int(bedrooms),
                bathrooms=int(bathrooms),
                property_type=property_type.lower() if property_type else "",
                area=area,
                address=address,
                postcode=postcode,
                url=url,
                image_url=image_url,
                description=description,
                sqm=sqm,
                sqm_source=sqm_source,
                epc_rating=epc.upper() if epc else "",
                lat=lat,
                lon=lon,
                tenure=tenure.lower() if tenure else "",
                floorplan_urls=floorplan_urls,
                agent_name=agent_name,
                agent_phone=agent_phone,
                **features_detected,
            )

        except Exception as e:
            self.logger.debug(f"Error parsing OnTheMarket JSON property: {e}")
            return None

    def _parse_jsonld_property(self, data: dict) -> Optional[Property]:
        """Parse a property from JSON-LD schema data."""
        try:
            # JSON-LD uses schema.org vocabulary
            prop_id = str(data.get("@id", "") or data.get("url", "")).split("/")[-1]
            if not prop_id:
                return None

            address_data = data.get("address", {})
            address = ""
            if isinstance(address_data, dict):
                address = ", ".join(filter(None, [
                    address_data.get("streetAddress", ""),
                    address_data.get("addressLocality", ""),
                    address_data.get("postalCode", ""),
                ]))
            postcode = self._extract_postcode(address)

            price = 0
            offers = data.get("offers", {})
            if isinstance(offers, dict):
                price = self._normalize_price(str(offers.get("price", "")))

            url = data.get("url", "")
            if url and not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"

            bedrooms = data.get("numberOfRooms", 0) or data.get("numberOfBedrooms", 0)

            return Property(
                id=Property.generate_id("onthemarket", prop_id),
                source="onthemarket",
                title=data.get("name", "") or address,
                price=int(price),
                bedrooms=int(bedrooms) if bedrooms else 0,
                address=address,
                postcode=postcode,
                area=self._extract_postcode_district(postcode or address),
                url=url,
            )

        except Exception as e:
            self.logger.debug(f"Error parsing JSON-LD property: {e}")
            return None

    def _parse_html_listings(self, soup: BeautifulSoup) -> list[Property]:
        """Fallback: parse listings from HTML cards."""
        properties = []

        card_selectors = [
            ".otm-PropertyCard",
            "[data-test='property-card']",
            ".property-result",
            ".listing-result",
        ]

        cards = []
        for selector in card_selectors:
            cards = soup.select(selector)
            if cards:
                self.logger.debug(f"Found {len(cards)} cards with: {selector}")
                break

        for card in cards:
            try:
                prop = self._parse_html_card(card)
                if prop:
                    properties.append(prop)
            except Exception as e:
                self.logger.debug(f"Error parsing OTM HTML card: {e}")

        return properties

    def _parse_html_card(self, card) -> Optional[Property]:
        """Parse a single property card from HTML."""
        try:
            # Link
            link = card.find("a", href=True)
            if not link:
                return None

            url = link.get("href", "")
            if url and not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"

            if not url or "/details/" not in url:
                return None

            # ID from URL
            id_match = re.search(r"/details/(\d+)", url)
            if not id_match:
                return None
            prop_id = id_match.group(1)

            # Address
            addr_elem = card.find(["h2", "h3", ".otm-PropertyCard__address", "[data-test='address']"])
            address = addr_elem.get_text(strip=True) if addr_elem else ""

            # Price
            price = 0
            price_elem = card.find(attrs={"class": re.compile(r"price", re.I)})
            if not price_elem:
                price_elem = card.find(string=re.compile(r"£"))
            if price_elem:
                price_text = price_elem.get_text() if hasattr(price_elem, "get_text") else str(price_elem)
                price = self._normalize_price(price_text)

            # Bedrooms
            bedrooms = -1
            bed_elem = card.find(string=re.compile(r"\d+\s*bed", re.I))
            if bed_elem:
                bedrooms = self._extract_bedrooms(str(bed_elem))

            # Lat/lon from data attributes
            lat = float(card.get("data-lat", 0) or 0)
            lon = float(card.get("data-lng", 0) or card.get("data-lon", 0) or 0)

            # Image
            img = card.find("img")
            image_url = img.get("src", "") or img.get("data-src", "") if img else ""

            # EPC badge
            epc = ""
            epc_elem = card.find(string=re.compile(r"EPC\s*[A-G]", re.I))
            if epc_elem:
                epc_match = re.search(r"EPC\s*([A-G])", str(epc_elem), re.I)
                if epc_match:
                    epc = epc_match.group(1).upper()

            postcode = self._extract_postcode(address)
            area = self._extract_postcode_district(address)

            return Property(
                id=Property.generate_id("onthemarket", prop_id),
                source="onthemarket",
                title=address,
                price=price,
                bedrooms=bedrooms if bedrooms >= 0 else 0,
                address=address,
                postcode=postcode,
                area=area,
                url=url,
                image_url=image_url,
                epc_rating=epc,
                lat=lat,
                lon=lon,
            )

        except Exception as e:
            self.logger.debug(f"Error parsing OTM HTML card: {e}")
            return None
