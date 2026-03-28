"""Tests for Property data model."""

from datetime import datetime
from core.models import Property


def test_property_creation():
    p = Property(
        id="rightmove_123",
        source="rightmove",
        title="2 bed flat in NW3",
        price=500000,
        bedrooms=2,
    )
    assert p.id == "rightmove_123"
    assert p.price == 500000
    assert p.sqm == 0.0
    assert p.price_per_sqm is None


def test_price_per_sqm():
    p = Property(id="t1", source="test", title="t", price=500000, bedrooms=2, sqm=80)
    assert p.price_per_sqm == 6250.0


def test_price_per_sqm_no_sqm():
    p = Property(id="t2", source="test", title="t", price=500000, bedrooms=2)
    assert p.price_per_sqm is None


def test_to_dict_roundtrip():
    p = Property(
        id="rm_1", source="rightmove", title="Flat",
        price=475000, bedrooms=3, sqm=90, epc_rating="B",
        first_seen=datetime(2024, 1, 15, 10, 30),
    )
    d = p.to_dict()
    assert d["price_per_sqm"] is not None
    assert d["first_seen"] == "2024-01-15T10:30:00"

    p2 = Property.from_dict(d)
    assert p2.id == p.id
    assert p2.price == p.price
    assert p2.sqm == p.sqm
    assert p2.first_seen == p.first_seen


def test_generate_id():
    assert Property.generate_id("zoopla", "456") == "zoopla_456"


def test_short_summary():
    p = Property(
        id="t", source="test", title="t", price=550000, bedrooms=2,
        sqm=80, epc_rating="C", nearest_station="Hampstead", walk_minutes=12,
    )
    s = p.short_summary()
    assert "\u00a3550,000" in s
    assert "2bed" in s
    assert "80m\u00b2" in s
    assert "EPC C" in s
    assert "Hampstead" in s
