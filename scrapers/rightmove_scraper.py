"""Scraper for Rightmove.co.uk property listings."""

import json
import logging
import re
from typing import Optional

from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

from core.models import Property
from scrapers.base_scraper import BaseScraper


class RightmoveScraper(BaseScraper):
    """Scraper for Rightmove using curl_cffi for browser impersonation."""

    BASE_URL = "https://www.rightmove.co.uk"

    @property
    def name(self) -> str:
        return "rightmove"

    def __init__(self, config: dict):
        super().__init__(config)
        self.session = curl_requests.Session(impersonate="chrome")

    def fetch_listings(self, area_config: dict) -> list[Property]:
        """Fetch listings for a specific area from Rightmove."""
        properties = []
        rightmove_id = area_config.get("rightmove_id", "")
        if not rightmove_id:
            self.logger.warning(f"No Rightmove ID for area: {area_config.get('name')}")
            return properties

        # Fetch 2-3 pages (24 results per page)
        for page_index in range(0, 72, 24):  # index 0, 24, 48
            try:
                page_props = self._fetch_page(rightmove_id, page_index)
                properties.extend(page_props)

                if len(page_props) == 0:
                    break

                if page_index < 48:
                    self._rate_limit()
            except Exception as e:
                self.logger.error(f"Error fetching Rightmove page index={page_index}: {e}")
                break

        self.logger.info(
            f"Fetched {len(properties)} listings from Rightmove "
            f"for {area_config.get('name', rightmove_id)}"
        )
        return properties

    def _fetch_page(self, location_id: str, index: int) -> list[Property]:
        """Fetch a single page of Rightmove results."""
        url = self._build_search_url(location_id, index)
        self.logger.debug(f"Fetching: {url}")

        headers = {
            "Referer": f"{self.BASE_URL}/",
            "Sec-Fetch-Site": "same-origin",
        }

        response = self.session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        self._request_count += 1

        return self._extract_listings(response.text)

    def _build_search_url(self, location_id: str, index: int = 0) -> str:
        """Build Rightmove search URL with filters."""
        params = [
            f"locationIdentifier={location_id}",
            f"index={index}",
            f"minBedrooms={self.config.get('bedrooms_min', 1)}",
            f"maxBedrooms={self.config.get('bedrooms_max', 4)}",
            f"minPrice={self.config.get('price_min', 0)}",
            f"maxPrice={self.config.get('price_max', 1000000)}",
            "propertyTypes=flat",
            "includeSSTC=false",
            "dontShow=retirement%2CsharedOwnership",
            "sortType=6",  # Most recent first
            "channel=BUY",
        ]
        return f"{self.BASE_URL}/property-for-sale/find.html?{'&'.join(params)}"

    def _extract_listings(self, html: str) -> list[Property]:
        """Extract listings from Rightmove HTML page."""
        properties = []
        soup = BeautifulSoup(html, "lxml")

        # Primary: __NEXT_DATA__ (current Rightmove)
        next_data = soup.find("script", id="__NEXT_DATA__")
        if next_data and next_data.string:
            try:
                data = json.loads(next_data.string)
                sr = data.get("props", {}).get("pageProps", {}).get("searchResults", {})
                listings = sr.get("properties", [])
                self.logger.info(f"__NEXT_DATA__ found with {len(listings)} properties")
                for item in listings:
                    prop = self._parse_json_property(item)
                    if prop:
                        properties.append(prop)
                if properties:
                    return properties
            except (json.JSONDecodeError, KeyError) as e:
                self.logger.warning(f"Error parsing __NEXT_DATA__: {e}")

        # Fallback: window.jsonModel (legacy)
        for script in soup.find_all("script"):
            text = script.string or ""
            if "window.jsonModel" in text:
                try:
                    match = re.search(r"window\.jsonModel\s*=\s*(\{.*\})", text, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                        listings = data.get("properties", [])
                        for item in listings:
                            prop = self._parse_json_property(item)
                            if prop:
                                properties.append(prop)
                        if properties:
                            return properties
                except (json.JSONDecodeError, KeyError) as e:
                    self.logger.warning(f"Error parsing jsonModel: {e}")

        # Final fallback: HTML cards
        properties = self._parse_html_listings(soup)
        return properties

    def _parse_json_property(self, data: dict) -> Optional[Property]:
        """Parse a single property from Rightmove JSON data."""
        try:
            prop_id = str(data.get("id", ""))
            if not prop_id:
                return None

            # Price
            price_data = data.get("price", {})
            if isinstance(price_data, dict):
                price = price_data.get("amount", 0)
                if not price:
                    price = self._normalize_price(price_data.get("displayPrices", [{}])[0].get("displayPrice", ""))
            elif isinstance(price_data, (int, float)):
                price = int(price_data)
            else:
                price = self._normalize_price(str(price_data))

            # Address
            address = data.get("displayAddress", "") or data.get("address", "")
            postcode = self._extract_postcode(address)
            area = self._extract_postcode_district(address)

            # Bedrooms/bathrooms
            bedrooms = data.get("bedrooms", 0)
            bathrooms = data.get("bathrooms", 0)
            if isinstance(bedrooms, str):
                bedrooms = int(bedrooms) if bedrooms.isdigit() else 0
            if isinstance(bathrooms, str):
                bathrooms = int(bathrooms) if bathrooms.isdigit() else 0

            # URL
            url = data.get("propertyUrl", "")
            if url and not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"

            # Images
            images = data.get("propertyImages", {})
            image_url = ""
            if isinstance(images, dict):
                main_img = images.get("mainImageSrc", "")
                image_url = main_img
            elif isinstance(images, list) and images:
                image_url = images[0] if isinstance(images[0], str) else images[0].get("url", "")

            # Floorplan URLs
            floorplan_urls = []
            floorplans = data.get("floorplanImages", []) or data.get("floorplans", [])
            for fp in floorplans:
                if isinstance(fp, str):
                    floorplan_urls.append(fp)
                elif isinstance(fp, dict):
                    fp_url = fp.get("url", "") or fp.get("src", "")
                    if fp_url:
                        floorplan_urls.append(fp_url)

            # Floorplan count and image count from metadata
            num_floorplans = data.get("numberOfFloorplans", 0) or 0
            num_images = data.get("numberOfImages", 0) or 0

            # displaySize (e.g. "682 sq. ft.")
            display_size = data.get("displaySize", "") or ""

            # Description and feature detection
            # keyFeatures can be list of dicts or strings
            raw_features = data.get("keyFeatures", []) or []
            key_features = []
            for kf in raw_features:
                if isinstance(kf, dict):
                    key_features.append(kf.get("description", ""))
                elif isinstance(kf, str):
                    key_features.append(kf)

            summary = data.get("summary", "") or data.get("description", "")
            combined_text = f"{summary} {' '.join(key_features)}"
            features_detected = self._detect_features(combined_text)

            # Property type
            property_type = data.get("propertySubType", "") or data.get("propertyType", "")

            # Lat/lon
            location = data.get("location", {})
            lat = location.get("latitude", 0) or 0
            lon = location.get("longitude", 0) or 0

            # Tenure (can be dict like {'tenureType': 'LEASEHOLD'} or string)
            tenure_data = data.get("tenure", "")
            if isinstance(tenure_data, dict):
                tenure = tenure_data.get("tenureType", "")
            else:
                tenure = str(tenure_data) if tenure_data else ""

            # Agent
            agent = data.get("customer", {}) or data.get("agent", {})
            agent_name = ""
            agent_phone = ""
            if isinstance(agent, dict):
                agent_name = agent.get("branchDisplayName", "") or agent.get("name", "")
                agent_phone = agent.get("contactTelephone", "") or agent.get("phone", "")

            # EPC from description/features
            epc = self._extract_epc(combined_text)

            # sqm: prefer displaySize, fallback to description
            sqm, sqm_source = 0.0, ""
            if display_size:
                sqm, sqm_source = self._extract_sqm_from_text(display_size)
            if not sqm:
                sqm, sqm_source = self._extract_sqm_from_text(combined_text)

            return Property(
                id=Property.generate_id("rightmove", prop_id),
                source="rightmove",
                title=f"{bedrooms} bed {property_type.lower()} - {address}" if bedrooms else address,
                price=int(price) if price else 0,
                bedrooms=int(bedrooms),
                bathrooms=int(bathrooms),
                property_type=property_type.lower(),
                area=area,
                address=address,
                postcode=postcode,
                url=url,
                image_url=image_url,
                description=combined_text,
                features=key_features,
                sqm=sqm,
                sqm_source=sqm_source,
                epc_rating=epc,
                lat=float(lat),
                lon=float(lon),
                tenure=tenure.lower() if tenure else "",
                floorplan_urls=floorplan_urls,
                num_images=int(num_images),
                num_floorplans=int(num_floorplans),
                agent_name=agent_name,
                agent_phone=agent_phone,
                **features_detected,
            )

        except Exception as e:
            self.logger.debug(f"Error parsing Rightmove JSON property: {e}")
            return None

    def _parse_html_listings(self, soup: BeautifulSoup) -> list[Property]:
        """Fallback: parse listings from HTML cards."""
        properties = []

        card_selectors = [
            ".l-searchResult",
            "[data-test='propertyCard']",
            ".propertyCard",
        ]

        cards = []
        for selector in card_selectors:
            cards = soup.select(selector)
            if cards:
                self.logger.debug(f"Found {len(cards)} cards with selector: {selector}")
                break

        for card in cards:
            try:
                prop = self._parse_html_card(card)
                if prop:
                    properties.append(prop)
            except Exception as e:
                self.logger.debug(f"Error parsing HTML card: {e}")

        return properties

    def _parse_html_card(self, card) -> Optional[Property]:
        """Parse a single property card from HTML."""
        try:
            link = card.find("a", href=True)
            if not link:
                return None

            url = link.get("href", "")
            if url and not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"

            if not url or "/properties/" not in url:
                return None

            # Extract ID from URL
            id_match = re.search(r"/properties/(\d+)", url)
            if not id_match:
                return None
            prop_id = id_match.group(1)

            # Title/address
            title_elem = card.find(["h2", "h3", "[data-test='address']"])
            address = title_elem.get_text(strip=True) if title_elem else ""

            # Price
            price = 0
            price_elem = card.find(string=re.compile(r"[£\d]")) or card.find(
                attrs={"class": re.compile(r"price")}
            )
            if price_elem:
                price_text = price_elem.get_text() if hasattr(price_elem, "get_text") else str(price_elem)
                price = self._normalize_price(price_text)

            # Bedrooms
            bedrooms = -1
            bed_elem = card.find(string=re.compile(r"\d+\s*bed", re.I))
            if bed_elem:
                bedrooms = self._extract_bedrooms(str(bed_elem))

            # Image
            img = card.find("img")
            image_url = img.get("src", "") if img else ""

            postcode = self._extract_postcode(address)
            area = self._extract_postcode_district(address)

            return Property(
                id=Property.generate_id("rightmove", prop_id),
                source="rightmove",
                title=address,
                price=price,
                bedrooms=bedrooms if bedrooms >= 0 else 0,
                address=address,
                postcode=postcode,
                area=area,
                url=url,
                image_url=image_url,
            )

        except Exception as e:
            self.logger.debug(f"Error parsing HTML card: {e}")
            return None
