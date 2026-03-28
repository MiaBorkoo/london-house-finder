"""Tests for property filter."""

from core.models import Property
from core.filter import PropertyFilter


def _make_config(**overrides):
    config = {
        "search": {
            "price_min": 400000,
            "price_max": 650000,
            "bedrooms_min": 2,
            "bedrooms_max": 3,
            "sqm_min": 78,
            "epc_min": "C",
            "must_have": ["garden"],
            "exclude_keywords": ["shared ownership", "retirement"],
        },
        "areas": [
            {"name": "Hampstead", "postcode": "NW3"},
            {"name": "Highgate", "postcode": "N6"},
        ],
        "hot_listing": {
            "price_below": 550000,
            "keywords": ["chain free"],
        },
    }
    config.update(overrides)
    return config


def _make_prop(**overrides):
    defaults = dict(
        id="t1", source="rightmove", title="Test flat",
        price=500000, bedrooms=2, area="NW3", postcode="NW3 2AA",
        has_garden=True,
    )
    defaults.update(overrides)
    return Property(**defaults)


def test_passes_valid():
    f = PropertyFilter(_make_config())
    passed, reason = f.passes(_make_prop())
    assert passed, reason


def test_fails_price_too_high():
    f = PropertyFilter(_make_config())
    passed, reason = f.passes(_make_prop(price=700000))
    assert not passed
    assert "700,000" in reason


def test_fails_price_too_low():
    f = PropertyFilter(_make_config())
    passed, reason = f.passes(_make_prop(price=300000))
    assert not passed
    assert "300,000" in reason


def test_unknown_price_passes():
    f = PropertyFilter(_make_config())
    passed, _ = f.passes(_make_prop(price=0))
    assert passed


def test_fails_too_few_beds():
    f = PropertyFilter(_make_config())
    passed, reason = f.passes(_make_prop(bedrooms=1))
    assert not passed
    assert "beds" in reason


def test_fails_too_many_beds():
    f = PropertyFilter(_make_config())
    passed, reason = f.passes(_make_prop(bedrooms=5))
    assert not passed


def test_fails_wrong_area():
    f = PropertyFilter(_make_config())
    passed, reason = f.passes(_make_prop(area="SW1", postcode="SW1A 1AA"))
    assert not passed
    assert "not in allowed" in reason


def test_fails_excluded_keyword():
    f = PropertyFilter(_make_config())
    passed, reason = f.passes(_make_prop(title="Shared ownership flat"))
    assert not passed
    assert "shared ownership" in reason


def test_fails_epc_too_low():
    f = PropertyFilter(_make_config())
    passed, reason = f.passes(_make_prop(epc_rating="E"))
    assert not passed
    assert "EPC" in reason


def test_unknown_epc_passes():
    f = PropertyFilter(_make_config())
    passed, _ = f.passes(_make_prop(epc_rating=""))
    assert passed


def test_fails_sqm_too_small():
    f = PropertyFilter(_make_config())
    passed, reason = f.passes(_make_prop(sqm=50))
    assert not passed
    assert "m\u00b2" in reason


def test_unknown_sqm_passes():
    f = PropertyFilter(_make_config())
    passed, _ = f.passes(_make_prop(sqm=0))
    assert passed


def test_must_have_garden_flag():
    f = PropertyFilter(_make_config())
    passed, _ = f.passes(_make_prop(has_garden=True))
    assert passed


def test_must_have_garden_description():
    f = PropertyFilter(_make_config())
    passed, _ = f.passes(_make_prop(has_garden=False, description="lovely rear garden"))
    assert passed


def test_must_have_fails():
    f = PropertyFilter(_make_config())
    # With description present but no garden/balcony mentioned, should fail
    passed, reason = f.passes(_make_prop(has_garden=False, description="a nice flat with parking"))
    assert not passed
    assert "must-have" in reason


def test_must_have_benefit_of_doubt():
    f = PropertyFilter(_make_config())
    # No description and no flags = benefit of the doubt
    passed, _ = f.passes(_make_prop(has_garden=False))
    assert passed


def test_hot_listing_price():
    f = PropertyFilter(_make_config())
    assert f.is_hot(_make_prop(price=480000))
    assert not f.is_hot(_make_prop(price=600000))


def test_hot_listing_keyword():
    f = PropertyFilter(_make_config())
    assert f.is_hot(_make_prop(price=600000, title="Chain free 2 bed flat"))
    assert not f.is_hot(_make_prop(price=600000, title="Regular flat"))
