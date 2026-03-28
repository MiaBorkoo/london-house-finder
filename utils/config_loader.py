"""Configuration loader with Google Sheets (primary) and YAML (fallback)."""

import csv
import io
import logging
import os

import requests
import yaml

logger = logging.getLogger(__name__)

SHEETS_CSV_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={tab}"


class ConfigLoader:
    """Load configuration from Google Sheets or local YAML."""

    def __init__(self, yaml_path: str = "config/config.yaml"):
        self.yaml_path = yaml_path
        self.sheet_id = os.environ.get("CONFIG_SHEET_ID", "")

    def load(self) -> dict:
        """Load config, trying Google Sheets first then YAML fallback."""
        if self.sheet_id:
            try:
                config = self._load_from_sheets()
                logger.info("Configuration loaded from Google Sheets")
                return config
            except Exception as e:
                logger.warning(f"Failed to load from Google Sheets: {e}")
                logger.info("Falling back to local YAML config")

        return self._load_from_yaml()

    def _load_from_sheets(self) -> dict:
        """Fetch and parse config from a public Google Sheet."""
        settings = self._fetch_sheet_tab("Settings")
        areas = self._fetch_sheet_tab("Areas")
        stations = self._fetch_sheet_tab("Target Stations")

        config = self._parse_settings(settings)
        config["areas"] = self._parse_areas(areas)
        config["stations"] = self._parse_stations(stations)
        config["_source"] = "google_sheets"
        return config

    def _fetch_sheet_tab(self, tab_name: str) -> list[dict]:
        """Fetch a single tab from the Google Sheet as CSV."""
        url = SHEETS_CSV_URL.format(sheet_id=self.sheet_id, tab=tab_name)
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        return list(reader)

    def _parse_settings(self, rows: list[dict]) -> dict:
        """Parse key-value Settings tab into config dict."""
        config = {}
        for row in rows:
            key = row.get("Key", "").strip()
            value = row.get("Value", "").strip()
            if not key:
                continue
            # Try to parse as int
            try:
                config[key] = int(value)
                continue
            except ValueError:
                pass
            # Try to parse as float
            try:
                config[key] = float(value)
                continue
            except ValueError:
                pass
            # Parse comma-separated as list
            if "," in value:
                config[key] = [v.strip() for v in value.split(",") if v.strip()]
            elif value.lower() in ("true", "false"):
                config[key] = value.lower() == "true"
            else:
                config[key] = value
        return config

    def _parse_areas(self, rows: list[dict]) -> list[dict]:
        """Parse Areas tab into list of area configs."""
        areas = []
        for row in rows:
            enabled = row.get("Enabled", "TRUE").strip().upper()
            if enabled != "TRUE":
                continue
            areas.append({
                "name": row.get("Area Name", "").strip(),
                "postcode": row.get("Postcode", "").strip(),
                "rightmove_id": row.get("Rightmove ID", "").strip(),
                "zoopla_query": row.get("Zoopla Query", "").strip(),
                "onthemarket_outcode": row.get("OnTheMarket Outcode", "").strip(),
            })
        return areas

    def _parse_stations(self, rows: list[dict]) -> list[dict]:
        """Parse Target Stations tab into list of station configs."""
        stations = []
        for row in rows:
            try:
                stations.append({
                    "name": row.get("Station Name", "").strip(),
                    "lat": float(row.get("Latitude", 0)),
                    "lon": float(row.get("Longitude", 0)),
                    "max_walk_minutes": int(row.get("Max Walk Minutes", 20)),
                })
            except (ValueError, TypeError) as e:
                logger.warning(f"Skipping invalid station row: {row} ({e})")
        return stations

    def _load_from_yaml(self) -> dict:
        """Load config from local YAML file."""
        with open(self.yaml_path, "r") as f:
            config = yaml.safe_load(f)
        config["_source"] = "yaml"
        logger.info(f"Configuration loaded from {self.yaml_path}")
        return config
