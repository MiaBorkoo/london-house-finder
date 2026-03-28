"""Tests for database module."""

import os
import pytest
from core.database import Database


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    return Database(db_path)


def test_init_creates_tables(db):
    stats = db.get_stats()
    assert stats["total"]["all_time"] == 0


def test_add_property(db):
    added = db.add_property({
        "id": "rm_1",
        "source": "rightmove",
        "title": "2 bed flat",
        "price": 500000,
        "bedrooms": 2,
        "url": "https://example.com/1",
    })
    assert added is True


def test_add_duplicate_rejected(db):
    prop = {
        "id": "rm_1",
        "source": "rightmove",
        "title": "2 bed flat",
        "price": 500000,
        "bedrooms": 2,
        "url": "https://example.com/1",
    }
    assert db.add_property(prop) is True
    assert db.add_property(prop) is False


def test_listing_exists(db):
    assert db.listing_exists("rm_1") is False
    db.add_property({"id": "rm_1", "source": "rightmove", "title": "t", "price": 0, "bedrooms": 0})
    assert db.listing_exists("rm_1") is True


def test_get_property(db):
    db.add_property({
        "id": "rm_1", "source": "rightmove", "title": "Nice flat",
        "price": 475000, "bedrooms": 3, "features": ["garden", "parking"],
    })
    prop = db.get_property("rm_1")
    assert prop is not None
    assert prop["price"] == 475000
    assert isinstance(prop["features"], list)
    assert "garden" in prop["features"]


def test_get_property_not_found(db):
    assert db.get_property("nonexistent") is None


def test_mark_notified_instant(db):
    db.add_property({"id": "rm_1", "source": "rightmove", "title": "t", "price": 0, "bedrooms": 0})
    db.mark_notified_instant("rm_1")
    prop = db.get_property("rm_1")
    assert prop["notified_instant"] is not None


def test_mark_digest_sent(db):
    db.add_property({"id": "rm_1", "source": "rightmove", "title": "t", "price": 0, "bedrooms": 0})
    db.add_property({"id": "rm_2", "source": "zoopla", "title": "t", "price": 0, "bedrooms": 0})
    db.mark_digest_sent(["rm_1", "rm_2"])
    p1 = db.get_property("rm_1")
    p2 = db.get_property("rm_2")
    assert p1["notified_digest"] is not None
    assert p2["notified_digest"] is not None


def test_update_enrichment(db):
    db.add_property({"id": "rm_1", "source": "rightmove", "title": "t", "price": 0, "bedrooms": 0})
    db.update_enrichment("rm_1", sqm=80, sqm_source="floorplan_ocr",
                         nearest_station="Hampstead", walk_minutes=12)
    prop = db.get_property("rm_1")
    assert prop["sqm"] == 80
    assert prop["sqm_source"] == "floorplan_ocr"
    assert prop["nearest_station"] == "Hampstead"
    assert prop["walk_minutes"] == 12


def test_get_recent_properties(db):
    db.add_property({"id": "rm_1", "source": "rightmove", "title": "t", "price": 500000, "bedrooms": 2})
    recent = db.get_recent_properties(hours=1)
    assert len(recent) == 1


def test_get_undigested_properties(db):
    db.add_property({"id": "rm_1", "source": "rightmove", "title": "t", "price": 0, "bedrooms": 0})
    undigested = db.get_undigested_properties()
    assert len(undigested) == 1

    db.mark_digest_sent(["rm_1"])
    undigested = db.get_undigested_properties()
    assert len(undigested) == 0


def test_cleanup_old_properties(db):
    db.add_property({"id": "rm_1", "source": "rightmove", "title": "t", "price": 0, "bedrooms": 0})
    # Won't delete recent properties
    count = db.cleanup_old_properties(days=1)
    assert count == 0
    assert db.listing_exists("rm_1")


def test_get_stats(db):
    db.add_property({"id": "rm_1", "source": "rightmove", "title": "t", "price": 500000, "bedrooms": 2})
    db.add_property({"id": "zp_1", "source": "zoopla", "title": "t2", "price": 600000, "bedrooms": 3})
    stats = db.get_stats()
    assert stats["total"]["all_time"] == 2
    assert stats["by_source"]["rightmove"] == 1
    assert stats["by_source"]["zoopla"] == 1
    assert stats["price"]["avg"] > 0
