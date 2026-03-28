"""Listing enricher that orchestrates distance calculation and floor plan analysis."""

import logging
from concurrent.futures import ThreadPoolExecutor
import time

from core.database import Database
from core.distance_calculator import DistanceCalculator
from core.models import Property
from enrichment.floorplan_analyzer import FloorplanAnalyzer

logger = logging.getLogger(__name__)


class ListingEnricher:
    """Enrich property listings with distance and sqm data."""

    def __init__(self, config: dict, database: Database):
        self.database = database
        stations = config.get("stations", [])
        self.distance_calc = DistanceCalculator(stations)
        self.floorplan_analyzer = FloorplanAnalyzer(config)

    def enrich(self, properties: list[Property]) -> list[Property]:
        """Enrich a batch of properties with distance + sqm data."""
        enriched_count = 0
        sqm_count = 0

        for prop in properties:
            changed = False

            # Distance calculation (instant, no API)
            if prop.lat and prop.lon and not prop.nearest_station:
                station, minutes = self.distance_calc.find_nearest_station(prop.lat, prop.lon)
                if station:
                    prop.nearest_station = station
                    prop.walk_minutes = minutes
                    changed = True

            # Floor plan analysis (may use API, rate limited)
            if prop.sqm <= 0 and prop.floorplan_urls:
                sqm, source = self.floorplan_analyzer.extract_sqm(prop.floorplan_urls)
                if sqm > 0:
                    prop.sqm = sqm
                    prop.sqm_source = source
                    sqm_count += 1
                    changed = True
                time.sleep(1)  # Rate limit between API calls

            if changed:
                self.database.update_enrichment(
                    prop.id,
                    sqm=prop.sqm,
                    sqm_source=prop.sqm_source,
                    nearest_station=prop.nearest_station,
                    walk_minutes=prop.walk_minutes,
                )
                enriched_count += 1

        logger.info(
            f"Enriched {enriched_count}/{len(properties)} properties, "
            f"{sqm_count} with sqm data"
        )
        return properties
