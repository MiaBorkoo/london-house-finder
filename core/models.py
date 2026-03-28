"""Property data model for London house listings."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Property:
    """Standardized property listing data structure for London purchases."""

    id: str
    source: str  # "rightmove", "zoopla", "onthemarket"
    title: str
    price: int  # Purchase price in GBP
    bedrooms: int
    bathrooms: int = 1
    property_type: str = ""  # flat, maisonette, terraced, etc.
    area: str = ""  # Postcode district e.g. "NW3"
    address: str = ""
    postcode: str = ""
    url: str = ""
    image_url: str = ""
    description: str = ""
    features: list = field(default_factory=list)
    # Purchase-specific fields
    sqm: float = 0.0
    sqm_source: str = ""  # "listing", "floorplan_vision", "floorplan_ocr"
    epc_rating: str = ""  # A-G
    lat: float = 0.0
    lon: float = 0.0
    tenure: str = ""  # freehold, leasehold, share of freehold
    floorplan_urls: list = field(default_factory=list)
    has_garden: bool = False
    has_balcony: bool = False
    has_parking: bool = False
    is_chain_free: bool = False
    agent_name: str = ""
    agent_phone: str = ""
    nearest_station: str = ""
    walk_minutes: float = 0.0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None

    @property
    def price_per_sqm(self) -> Optional[float]:
        """Calculate price per square meter."""
        if self.sqm and self.sqm > 0 and self.price > 0:
            return round(self.price / self.sqm, 2)
        return None

    def to_dict(self) -> dict:
        """Convert property to dictionary for JSON serialization."""
        data = asdict(self)
        if self.first_seen:
            data["first_seen"] = self.first_seen.isoformat()
        if self.last_seen:
            data["last_seen"] = self.last_seen.isoformat()
        data["price_per_sqm"] = self.price_per_sqm
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Property":
        """Create a Property from a dictionary."""
        for field_name in ("first_seen", "last_seen"):
            val = data.get(field_name)
            if isinstance(val, str):
                data[field_name] = datetime.fromisoformat(val)
        # Remove computed fields that aren't constructor args
        data.pop("price_per_sqm", None)
        # Only pass known fields
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    @staticmethod
    def generate_id(source: str, original_id: str) -> str:
        """Generate a unique property ID."""
        return f"{source}_{original_id}"

    def short_summary(self) -> str:
        """One-line summary for notifications."""
        parts = [f"\u00a3{self.price:,}"]
        if self.bedrooms >= 0:
            parts.append(f"{self.bedrooms}bed")
        if self.sqm > 0:
            parts.append(f"{self.sqm:.0f}m\u00b2")
        if self.epc_rating:
            parts.append(f"EPC {self.epc_rating}")
        if self.nearest_station:
            parts.append(f"{self.walk_minutes:.0f}min to {self.nearest_station}")
        return " | ".join(parts)
