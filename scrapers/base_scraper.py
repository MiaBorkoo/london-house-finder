"""Base scraper class for property websites."""

import logging
import random
import re
import time
from abc import ABC, abstractmethod
from typing import Optional

from core.models import Property


class BaseScraper(ABC):
    """Abstract base class for all property scrapers."""

    WORD_TO_NUM = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }

    USER_AGENTS = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    ]

    # UK postcode regex: e.g. NW3 2AA, SW1A 1AA, E1 6AN
    POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.IGNORECASE)
    # Postcode district only: NW3, SW1A, E1
    POSTCODE_DISTRICT_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\b", re.IGNORECASE)

    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.rate_limit_seconds = config.get("rate_limit_seconds", 3)
        self._request_count = 0

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def fetch_listings(self, area_config: dict) -> list[Property]:
        """Fetch listings for a specific area."""
        pass

    def _rate_limit(self) -> None:
        """Random delay between requests."""
        delay = self.rate_limit_seconds + random.uniform(0, 2)
        self.logger.debug(f"Rate limiting: {delay:.1f}s")
        time.sleep(delay)

    def _normalize_price(self, price_str: str) -> int:
        """Extract purchase price from string.

        Handles: "£475,000", "Offers over £500,000", "Guide price £650,000",
        "From £400,000", "475000"
        """
        if not price_str:
            return 0

        price_str = price_str.lower().replace(",", "").replace("£", "").replace("gbp", "")

        # Remove common prefixes
        for prefix in ("offers over", "guide price", "from", "asking price", "oieo", "price on application"):
            price_str = price_str.replace(prefix, "")

        # Extract the first large number (6+ digits for purchase prices)
        match = re.search(r"(\d{5,})", price_str.strip())
        if match:
            return int(match.group(1))

        # Try smaller numbers (might be in thousands format like "475")
        digits = re.findall(r"\d+", price_str)
        if digits:
            val = int(digits[0])
            # If suspiciously small, might be in thousands
            if val < 10000 and "k" in price_str:
                return val * 1000
            return val

        return 0

    def _extract_bedrooms(self, text: str) -> int:
        """Extract number of bedrooms from text. Returns -1 if unknown."""
        if not text:
            return -1

        text = text.lower()

        if re.search(r"\bstudio\b", text):
            return 0

        match = re.search(r"(\d+)\s*[-\s]?\s*bed(?:room)?s?\b", text)
        if match:
            return int(match.group(1))

        for word, num in self.WORD_TO_NUM.items():
            if re.search(rf"\b{word}\s*[-\s]?\s*bed(?:room)?s?\b", text):
                return num

        return -1

    def _extract_postcode(self, text: str) -> str:
        """Extract UK postcode from text. Returns full postcode or district."""
        if not text:
            return ""

        # Try full postcode first
        match = self.POSTCODE_RE.search(text)
        if match:
            return f"{match.group(1).upper()} {match.group(2).upper()}"

        # Try district only
        match = self.POSTCODE_DISTRICT_RE.search(text)
        if match:
            return match.group(1).upper()

        return ""

    def _extract_postcode_district(self, text: str) -> str:
        """Extract just the postcode district (e.g. NW3, E1, SW1A)."""
        if not text:
            return ""
        match = self.POSTCODE_DISTRICT_RE.search(text)
        return match.group(1).upper() if match else ""

    def _detect_features(self, description: str) -> dict:
        """Detect property features from description text."""
        desc = (description or "").lower()
        return {
            "has_garden": bool(re.search(
                r"\b(private garden|rear garden|communal garden|garden flat|south[- ]facing garden|garden)\b", desc
            )),
            "has_balcony": bool(re.search(
                r"\b(balcony|terrace|juliet balcony|roof terrace|private terrace)\b", desc
            )),
            "has_parking": bool(re.search(
                r"\b(parking|garage|off[- ]street|residents parking|allocated parking)\b", desc
            )),
            "is_chain_free": bool(re.search(
                r"\b(chain free|no chain|chain-free)\b", desc
            )),
        }

    def _extract_sqm_from_text(self, text: str) -> tuple[float, str]:
        """Extract square meters from listing text. Returns (sqm, source)."""
        if not text:
            return 0.0, ""

        # Look for sqm
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:sq\.?\s*m|m\u00b2|sqm)", text, re.IGNORECASE)
        if match:
            return float(match.group(1)), "listing"

        # Look for sq ft and convert
        match = re.search(r"(\d+(?:,\d+)?(?:\.\d+)?)\s*(?:sq\.?\s*ft|ft\u00b2|sqft)", text, re.IGNORECASE)
        if match:
            sqft = float(match.group(1).replace(",", ""))
            return round(sqft * 0.0929, 1), "listing"

        return 0.0, ""

    def _extract_epc(self, text: str) -> str:
        """Extract EPC rating from text."""
        if not text:
            return ""
        match = re.search(r"\bepc\s*(?:rating)?\s*:?\s*([A-G])\b", text, re.IGNORECASE)
        return match.group(1).upper() if match else ""

    def get_headers(self) -> dict[str, str]:
        return {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }
