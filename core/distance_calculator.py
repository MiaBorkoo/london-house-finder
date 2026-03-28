"""Distance calculator for walking distance to tube/rail stations."""

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0
WALKING_SPEED_KMH = 5.0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two points in km."""
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_KM * c


def walking_minutes(distance_km: float, speed_kmh: float = WALKING_SPEED_KMH) -> float:
    """Convert distance to approximate walking time in minutes."""
    return math.ceil((distance_km / speed_kmh) * 60)


class DistanceCalculator:
    """Calculate walking distance from properties to target stations."""

    def __init__(self, stations: list[dict]):
        """Initialize with list of station dicts: {name, lat, lon, max_walk_minutes}."""
        self.stations = stations
        if not stations:
            logger.warning("No target stations configured")

    def find_nearest_station(
        self, lat: float, lon: float
    ) -> tuple[Optional[str], Optional[float]]:
        """Find the nearest station within walking distance.

        Returns:
            (station_name, walk_minutes) or (None, None) if too far from all.
        """
        if not self.stations or lat == 0 or lon == 0:
            return None, None

        nearest_name = None
        nearest_minutes = float("inf")

        for station in self.stations:
            s_lat = station.get("lat", 0)
            s_lon = station.get("lon", 0)
            max_walk = station.get("max_walk_minutes", 20)

            if s_lat == 0 or s_lon == 0:
                continue

            dist_km = haversine(lat, lon, s_lat, s_lon)
            walk_min = walking_minutes(dist_km)

            if walk_min <= max_walk and walk_min < nearest_minutes:
                nearest_name = station["name"]
                nearest_minutes = walk_min

        if nearest_name:
            return nearest_name, nearest_minutes
        return None, None
