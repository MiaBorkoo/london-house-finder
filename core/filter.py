"""Filter module for filtering property listings based on search criteria."""

import logging
import re

from core.models import Property


EPC_ORDER = ["A", "B", "C", "D", "E", "F", "G"]


class PropertyFilter:
    """Filter for checking if a property matches search criteria."""

    def __init__(self, config: dict):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.config = config

        search = config.get("search", {})
        self.price_min = search.get("price_min", 0)
        self.price_max = search.get("price_max", float("inf"))
        self.bedrooms_min = search.get("bedrooms_min", 0)
        self.bedrooms_max = search.get("bedrooms_max", float("inf"))
        self.sqm_min = search.get("sqm_min", 0)
        self.epc_min = search.get("epc_min", "")
        self.must_have = [f.lower() for f in search.get("must_have", [])]
        self.exclude_keywords = [k.lower() for k in search.get("exclude_keywords", [])]

        # Area postcodes from areas config
        self.allowed_postcodes = set()
        for area in config.get("areas", []):
            pc = area.get("postcode", "").strip().upper()
            if pc:
                self.allowed_postcodes.add(pc)

        # Hot listing criteria
        hot = config.get("hot_listing", {})
        self.hot_price_below = hot.get("price_below", 0)
        self.hot_keywords = [k.lower() for k in hot.get("keywords", [])]

    def passes(self, prop: Property) -> tuple[bool, str]:
        """Check if a property passes all filters. Returns (passes, reason)."""
        checks = [
            self._check_price,
            self._check_bedrooms,
            self._check_area,
            self._check_sqm,
            self._check_epc,
            self._check_exclusions,
            self._check_must_have,
        ]

        for check in checks:
            passed, reason = check(prop)
            if not passed:
                return False, reason

        return True, ""

    def is_hot(self, prop: Property) -> bool:
        """Check if a property qualifies as a hot listing for instant alerts."""
        if self.hot_price_below and 0 < prop.price < self.hot_price_below:
            return True

        text = f"{prop.title} {prop.description}".lower()
        for keyword in self.hot_keywords:
            if keyword in text:
                return True

        return False

    def _check_price(self, prop: Property) -> tuple[bool, str]:
        if prop.price == 0:
            return True, ""
        if prop.price > self.price_max:
            return False, f"Price \u00a3{prop.price:,} > max \u00a3{self.price_max:,}"
        if prop.price < self.price_min:
            return False, f"Price \u00a3{prop.price:,} < min \u00a3{self.price_min:,}"
        return True, ""

    def _check_bedrooms(self, prop: Property) -> tuple[bool, str]:
        if prop.bedrooms < 0:
            return True, ""
        if prop.bedrooms < self.bedrooms_min:
            return False, f"{prop.bedrooms} beds < min {self.bedrooms_min}"
        if prop.bedrooms > self.bedrooms_max:
            return False, f"{prop.bedrooms} beds > max {self.bedrooms_max}"
        return True, ""

    def _check_area(self, prop: Property) -> tuple[bool, str]:
        """Check if property is in an allowed postcode district."""
        if not self.allowed_postcodes:
            return True, ""

        # Check postcode district against allowed list
        postcode_district = ""
        if prop.postcode:
            match = re.match(r"([A-Z]{1,2}\d[A-Z\d]?)", prop.postcode.upper())
            if match:
                postcode_district = match.group(1)
        if not postcode_district and prop.area:
            postcode_district = prop.area.upper()

        if postcode_district and postcode_district in self.allowed_postcodes:
            return True, ""

        # Also check address text for any allowed postcode
        location_text = f"{prop.area} {prop.address} {prop.postcode}".upper()
        for pc in self.allowed_postcodes:
            if re.search(rf"\b{re.escape(pc)}\b", location_text):
                return True, ""

        return False, f"Postcode '{postcode_district or prop.address}' not in allowed areas"

    def _check_sqm(self, prop: Property) -> tuple[bool, str]:
        if not self.sqm_min or prop.sqm <= 0:
            return True, ""  # Benefit of the doubt if unknown
        if prop.sqm < self.sqm_min:
            return False, f"{prop.sqm:.0f}m\u00b2 < min {self.sqm_min}m\u00b2"
        return True, ""

    def _check_epc(self, prop: Property) -> tuple[bool, str]:
        if not self.epc_min or not prop.epc_rating:
            return True, ""  # Benefit of the doubt if unknown
        try:
            prop_idx = EPC_ORDER.index(prop.epc_rating.upper())
            min_idx = EPC_ORDER.index(self.epc_min.upper())
            if prop_idx > min_idx:  # Higher index = worse rating
                return False, f"EPC {prop.epc_rating} worse than min {self.epc_min}"
        except ValueError:
            pass
        return True, ""

    def _check_exclusions(self, prop: Property) -> tuple[bool, str]:
        if not self.exclude_keywords:
            return True, ""
        text = f"{prop.title} {prop.description}".lower()
        for keyword in self.exclude_keywords:
            if keyword in text:
                return False, f"Contains excluded keyword: '{keyword}'"
        return True, ""

    def _check_must_have(self, prop: Property) -> tuple[bool, str]:
        """Check must-have features. Uses OR logic: at least one must be present.

        If we have no description and no feature flags, give benefit of the doubt.
        """
        if not self.must_have:
            return True, ""

        # Check boolean flags
        feature_map = {
            "garden": prop.has_garden,
            "balcony": prop.has_balcony,
            "parking": prop.has_parking,
            "chain free": prop.is_chain_free,
        }

        for feature in self.must_have:
            if feature_map.get(feature, False):
                return True, ""

        # Check text in description + features
        features_text = " ".join(f.lower() for f in (prop.features or []))
        combined = f"{features_text} {prop.description or ''}".lower()

        # If no text to check, benefit of the doubt
        if not combined.strip():
            return True, ""

        for feature in self.must_have:
            if feature in combined:
                return True, ""

        return False, f"Missing all must-have features: {self.must_have}"
