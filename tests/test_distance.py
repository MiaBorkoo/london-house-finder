"""Tests for distance calculator."""

from core.distance_calculator import haversine, walking_minutes, DistanceCalculator


def test_haversine_known_distance():
    # Hampstead station to Belsize Park station: ~1.1-1.2km
    dist = haversine(51.5568, -0.1782, 51.5504, -0.1644)
    assert 0.8 < dist < 1.5


def test_haversine_zero_distance():
    dist = haversine(51.5, -0.1, 51.5, -0.1)
    assert dist == 0.0


def test_haversine_long_distance():
    # London to Paris: ~340km
    dist = haversine(51.5074, -0.1278, 48.8566, 2.3522)
    assert 330 < dist < 360


def test_walking_minutes():
    # 1km at 5km/h = 12 minutes
    mins = walking_minutes(1.0)
    assert mins == 12


def test_walking_minutes_short():
    mins = walking_minutes(0.1)
    assert mins >= 1


def test_nearest_station_found():
    stations = [
        {"name": "Hampstead", "lat": 51.5568, "lon": -0.1782, "max_walk_minutes": 20},
        {"name": "Highgate", "lat": 51.5777, "lon": -0.1466, "max_walk_minutes": 20},
    ]
    calc = DistanceCalculator(stations)

    # Very close to Hampstead
    name, mins = calc.find_nearest_station(51.5565, -0.1780)
    assert name == "Hampstead"
    assert mins is not None and mins <= 5


def test_nearest_station_too_far():
    stations = [
        {"name": "Hampstead", "lat": 51.5568, "lon": -0.1782, "max_walk_minutes": 10},
    ]
    calc = DistanceCalculator(stations)

    # Central London, far from Hampstead
    name, mins = calc.find_nearest_station(51.5074, -0.1278)
    assert name is None
    assert mins is None


def test_no_coords():
    stations = [
        {"name": "Hampstead", "lat": 51.5568, "lon": -0.1782, "max_walk_minutes": 20},
    ]
    calc = DistanceCalculator(stations)
    name, mins = calc.find_nearest_station(0, 0)
    assert name is None


def test_no_stations():
    calc = DistanceCalculator([])
    name, mins = calc.find_nearest_station(51.5, -0.1)
    assert name is None
