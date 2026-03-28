"""Tests for configuration loader."""

import os
from utils.config_loader import ConfigLoader


def test_yaml_loading():
    loader = ConfigLoader("config/config.yaml")
    config = loader.load()
    assert config["_source"] == "yaml"
    assert "search" in config
    assert "areas" in config
    assert "stations" in config


def test_yaml_search_criteria():
    loader = ConfigLoader("config/config.yaml")
    config = loader.load()
    search = config["search"]
    assert search["price_min"] == 400000
    assert search["price_max"] == 650000
    assert search["bedrooms_min"] == 2
    assert search["bedrooms_max"] == 3


def test_yaml_areas():
    loader = ConfigLoader("config/config.yaml")
    config = loader.load()
    areas = config["areas"]
    assert len(areas) == 5
    assert "Hampstead" in areas[0]["name"]
    assert areas[0]["postcode"] == "NW3"


def test_yaml_stations():
    loader = ConfigLoader("config/config.yaml")
    config = loader.load()
    stations = config["stations"]
    assert len(stations) == 8
    assert stations[0]["name"] == "Golders Green"
    assert stations[0]["lat"] == 51.5724


def test_sheets_fallback_on_no_id():
    """Without CONFIG_SHEET_ID, should fall back to YAML."""
    old = os.environ.pop("CONFIG_SHEET_ID", None)
    try:
        loader = ConfigLoader("config/config.yaml")
        config = loader.load()
        assert config["_source"] == "yaml"
    finally:
        if old:
            os.environ["CONFIG_SHEET_ID"] = old
