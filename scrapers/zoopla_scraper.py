"""Scraper for Zoopla.co.uk property listings."""

import json
import logging
import re
from typing import Optional

from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

from core.models import Property
from scrapers.base_scraper import BaseScraper


class ZooplaScraper(BaseScraper):
    """Scraper for Zoopla using curl_cffi for browser impersonation."""

    BASE_URL = "https://www.zoopla.co.uk"

    @property
    def name(self) -> str:
        return "zoopla"

    def __init__(self, config: dict):
        super().__init__(config)
        self.session = curl_requests.Session(impersonate="chrome")

    def fetch_listings(self, area_config: dict) -> list[Property]:
        """Fetch listings for a specific area from Zoopla."""
        properties = []
        zoopla_query = area_config.get("zoopla_query", "")
        if not zoopla_query:
            self.logger.warning(f"No Zoopla query for area: {area_config.get('name')}")
            return properties

        for page_num in range(1, 4):  # Pages 1-3
            try:
                page_props = self._fetch_page(zoopla_query, page_num)
                properties.extend(page_props)

                if len(page_props) == 0:
                    break

                if page_num < 3:
                    self._rate_limit()
            except Exception as e:
                self.logger.error(f"Error fetching Zoopla page {page_num}: {e}")
                break

        self.logger.info(
            f"Fetched {len(properties)} listings from Zoopla "
            f"for {area_config.get('name', zoopla_query)}"
        )
        return properties

    def _fetch_page(self, area_query: str, page: int) -> list[Property]:
        """Fetch a single page of Zoopla results."""
        url = self._build_search_url(area_query, page)
        self.logger.debug(f"Fetching: {url}")

        headers = {
            "Referer": f"{self.BASE_URL}/",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        }

        response = self.session.get(url, headers=headers, timeout=30)
        self._request_count += 1

        # Check for CAPTCHA/block
        if response.status_code == 403:
            self.logger.warning("Zoopla returned 403 - likely bot detection")
            return []
        if "captcha" in response.text.lower() or "verify you are human" in response.text.lower():
            self.logger.warning("Zoopla CAPTCHA detected - stopping")
            return []

        response.raise_for_status()
        return self._extract_listings(response.text)

    def _build_search_url(self, area_query: str, page: int = 1) -> str:
        """Build Zoopla search URL with filters."""
        price_min = self.config.get("price_min", 0)
        price_max = self.config.get("price_max", 1000000)
        beds_min = self.config.get("bedrooms_min", 1)
        beds_max = self.config.get("bedrooms_max", 4)

        params = [
            f"price_min={price_min}",
            f"price_max={price_max}",
            f"beds_min={beds_min}",
            f"beds_max={beds_max}",
            "property_type=flats",
            "is_retirement_home=false",
            "is_shared_ownership=false",
            "results_sort=newest_listings",
            "search_source=for-sale",
        ]
        if page > 1:
            params.append(f"pn={page}")

        return f"{self.BASE_URL}/for-sale/flats/{area_query}/?{'&'.join(params)}"

    def _extract_listings(self, html: str) -> list[Property]:
        """Extract listings from Zoopla HTML page."""
        properties = []
        soup = BeautifulSoup(html, "lxml")

        # Primary: __NEXT_DATA__ JSON
        next_data = soup.find("script", id="__NEXT_DATA__")
        if next_data and next_data.string:
            try:
                data = json.loads(next_data.string)
                props = data.get("props", {}).get("pageProps", {})

                # Zoopla nests listings in various locations
                listings = (
                    props.get("regularListingsFormatted", [])
                    or props.get("listings", [])
                    or props.get("regularListings", [])
                    or self._find_listings_recursive(props)
                )

                for item in listings:
                    listing_data = item.get("listing", item) if isinstance(item, dict) else item
                    prop = self._parse_json_property(listing_data)
                    if prop:
                        properties.append(prop)

                if properties:
                    self.logger.debug(f"Extracted {len(properties)} from __NEXT_DATA__")
                    return properties

            except (json.JSONDecodeError, TypeError, KeyError) as e:
                self.logger.debug(f"Error parsing __NEXT_DATA__: {e}")

        # Fallback: parse script tags for embedded JSON
        for script in soup.find_all("script"):
            text = script.string or ""
            if "listingResults" in text or "searchResults" in text:
                try:
                    match = re.search(r"(\{.*\"listings?\".*\})", text, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                        listings = data.get("listings", data.get("listing", []))
                        if isinstance(listings, list):
                            for item in listings:
                                prop = self._parse_json_property(item)
                                if prop:
                                    properties.append(prop)
                        if properties:
                            return properties
                except (json.JSONDecodeError, KeyError):
                    pass

        # Final fallback: HTML card parsing
        properties = self._parse_html_listings(soup)
        return properties

    def _find_listings_recursive(self, data, depth: int = 0) -> list:
        """Recursively search for listings arrays in nested JSON."""
        if depth > 5:
            return []
        if isinstance(data, list) and data and isinstance(data[0], dict):
            if any(k in data[0] for k in ("listingId", "id", "price", "address")):
                return data
        if isinstance(data, dict):
            for key in ("listings", "regularListings", "results", "properties"):
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        return val
            for val in data.values():
                if isinstance(val, (dict, list)):
                    result = self._find_listings_recursive(val, depth + 1)
                    if result:
                        return result
        return []

    def _parse_json_property(self, data: dict) -> Optional[Property]:
        """Parse a single property from Zoopla JSON data."""
        try:
            if not isinstance(data, dict):
                return None

            # ID
            prop_id = str(
                data.get("listingId", "")
                or data.get("id", "")
                or data.get("listingUris", {}).get("detail", "").split("/")[-1]
                or ""
            )
            if not prop_id or prop_id == "":
                return None

            # Price
            price = 0
            price_data = data.get("price", {})
            if isinstance(price_data, dict):
                price = price_data.get("amount", 0) or price_data.get("value", 0)
                if not price:
                    price = self._normalize_price(price_data.get("displayPrice", ""))
            elif isinstance(price_data, (int, float)):
                price = int(price_data)
            elif isinstance(price_data, str):
                price = self._normalize_price(price_data)

            if price == 0:
                # Try alternative price fields
                price = self._normalize_price(str(data.get("displayPrice", "")))

            # Address
            address_data = data.get("address", "")
            if isinstance(address_data, dict):
                address = address_data.get("displayAddress", "") or ", ".join(
                    filter(None, [
                        address_data.get("streetAddress", ""),
                        address_data.get("locality", ""),
                        address_data.get("town", ""),
                        address_data.get("postcode", ""),
                    ])
                )
            else:
                address = str(address_data)

            postcode = self._extract_postcode(address)
            if not postcode and isinstance(address_data, dict):
                postcode = self._extract_postcode(address_data.get("postcode", ""))
            area = self._extract_postcode_district(postcode or address)

            # Bedrooms/bathrooms
            bedrooms = data.get("beds", 0) or data.get("bedrooms", 0) or data.get("num_beds", 0)
            bathrooms = data.get("baths", 0) or data.get("bathrooms", 0) or data.get("num_baths", 0)
            if isinstance(bedrooms, str):
                bedrooms = int(bedrooms) if bedrooms.isdigit() else 0
            if isinstance(bathrooms, str):
                bathrooms = int(bathrooms) if bathrooms.isdigit() else 0

            # URL
            url = ""
            uris = data.get("listingUris", {})
            if isinstance(uris, dict):
                url = uris.get("detail", "") or uris.get("contact", "")
            if not url:
                url = data.get("detailUrl", "") or data.get("url", "")
            if url and not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"
            if not url and prop_id:
                url = f"{self.BASE_URL}/for-sale/details/{prop_id}"

            # Image
            image_url = ""
            images = data.get("image", data.get("images", []))
            if isinstance(images, dict):
                image_url = images.get("src", "") or images.get("url", "")
            elif isinstance(images, list) and images:
                first = images[0]
                image_url = first.get("src", "") or first.get("url", "") if isinstance(first, dict) else str(first)
            elif isinstance(images, str):
                image_url = images

            # Floorplan
            floorplan_urls = []
            floorplans = data.get("floorPlan", data.get("floorPlans", []))
            if isinstance(floorplans, dict):
                fp_url = floorplans.get("src", "") or floorplans.get("url", "")
                if fp_url:
                    floorplan_urls.append(fp_url)
            elif isinstance(floorplans, list):
                for fp in floorplans:
                    fp_url = fp.get("src", "") or fp.get("url", "") if isinstance(fp, dict) else str(fp)
                    if fp_url:
                        floorplan_urls.append(fp_url)

            # Description and features
            description = data.get("summaryDescription", "") or data.get("description", "")
            features_detected = self._detect_features(description)

            # Property type
            property_type = data.get("propertyType", "") or data.get("property_type", "")

            # Location
            location = data.get("location", {}) or data.get("latLon", {})
            lat = 0.0
            lon = 0.0
            if isinstance(location, dict):
                lat = location.get("latitude", 0) or location.get("lat", 0) or 0
                lon = location.get("longitude", 0) or location.get("lng", 0) or location.get("lon", 0) or 0

            # Tenure
            tenure = data.get("tenure", "") or ""

            # EPC
            epc = self._extract_epc(description)

            # sqm
            sqm, sqm_source = self._extract_sqm_from_text(description)

            # Agent
            agent_data = data.get("branch", {}) or data.get("agent", {})
            agent_name = ""
            agent_phone = ""
            if isinstance(agent_data, dict):
                agent_name = agent_data.get("name", "") or agent_data.get("displayName", "")
                agent_phone = agent_data.get("phone", "") or agent_data.get("contactNumber", "")

            return Property(
                id=Property.generate_id("zoopla", prop_id),
                source="zoopla",
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
                epc_rating=epc,
                lat=float(lat),
                lon=float(lon),
                tenure=tenure.lower() if tenure else "",
                floorplan_urls=floorplan_urls,
                agent_name=agent_name,
                agent_phone=agent_phone,
                **features_detected,
            )

        except Exception as e:
            self.logger.debug(f"Error parsing Zoopla JSON property: {e}")
            return None

    def _parse_html_listings(self, soup: BeautifulSoup) -> list[Property]:
        """Fallback: parse listings from HTML cards."""
        properties = []

        card_selectors = [
            "[data-testid='search-result']",
            ".listing-results-wrapper .listing-result",
            "[data-testid='regular-listings'] > div",
            ".css-wfndrn",  # Zoopla uses CSS module class names
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
                self.logger.debug(f"Error parsing Zoopla HTML card: {e}")

        return properties

    def _parse_html_card(self, card) -> Optional[Property]:
        """Parse a single property card from HTML."""
        try:
            # Find link
            link = card.find("a", href=True)
            if not link:
                return None

            url = link.get("href", "")
            if url and not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"

            if not url or "/for-sale/" not in url:
                return None

            # ID from URL: /for-sale/details/12345678
            id_match = re.search(r"/details/(\d+)", url)
            if not id_match:
                id_match = re.search(r"/(\d{6,})", url)
            if not id_match:
                return None
            prop_id = id_match.group(1)

            # Address
            addr_elem = card.find(["h2", "h3", "[data-testid='listing-title']", "address"])
            address = addr_elem.get_text(strip=True) if addr_elem else ""

            # Price
            price = 0
            price_elem = card.find(string=re.compile(r"[£\d]"))
            if not price_elem:
                price_elem = card.find(attrs={"data-testid": re.compile(r"price")})
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
            image_url = img.get("src", "") or img.get("data-src", "") if img else ""

            postcode = self._extract_postcode(address)
            area = self._extract_postcode_district(address)

            return Property(
                id=Property.generate_id("zoopla", prop_id),
                source="zoopla",
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
            self.logger.debug(f"Error parsing Zoopla HTML card: {e}")
            return None
