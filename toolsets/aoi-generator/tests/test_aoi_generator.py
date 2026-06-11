import math

import pytest

from aoi_generator.tools import GAZETTEER, aoi_from_place, aoi_from_point


def test_place_returns_gazetteer_bbox():
    feature = aoi_from_place.invoke({"place": "alps"})
    assert feature["type"] == "Feature"
    assert feature["bbox"] == [5.0, 44.0, 16.0, 48.0]
    ring = feature["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1] == [5.0, 44.0]
    assert len(ring) == 5


def test_place_is_normalized():
    feature = aoi_from_place.invoke({"place": "  Iberian Peninsula "})
    assert feature["properties"]["place"] == "iberian-peninsula"


def test_place_buffer_expands_bbox():
    plain = aoi_from_place.invoke({"place": "bologna"})
    buffered = aoi_from_place.invoke({"place": "bologna", "buffer_km": 10.0})
    west, south, east, north = plain["bbox"]
    bwest, bsouth, beast, bnorth = buffered["bbox"]
    assert bwest < west and bsouth < south and beast > east and bnorth > north
    assert bnorth - north == pytest.approx(10.0 / 110.574)


def test_place_unknown_lists_known():
    with pytest.raises(ValueError, match="known places") as excinfo:
        aoi_from_place.invoke({"place": "atlantis"})
    assert "alps" in str(excinfo.value)


def test_place_negative_buffer_rejected():
    with pytest.raises(ValueError, match="buffer_km"):
        aoi_from_place.invoke({"place": "alps", "buffer_km": -1.0})


def test_point_bbox_centred_on_point():
    feature = aoi_from_point.invoke({"lat": 44.5, "lon": 11.3, "radius_km": 25.0})
    west, south, east, north = feature["bbox"]
    assert (west + east) / 2 == pytest.approx(11.3)
    assert (south + north) / 2 == pytest.approx(44.5)
    assert north - south == pytest.approx(2 * 25.0 / 110.574)
    expected_dlon = 25.0 / (111.320 * math.cos(math.radians(44.5)))
    assert east - west == pytest.approx(2 * expected_dlon)


def test_point_clamps_at_poles():
    feature = aoi_from_point.invoke({"lat": 89.9, "lon": 0.0, "radius_km": 100.0})
    west, south, east, north = feature["bbox"]
    assert north == 90.0
    assert west >= -180.0 and east <= 180.0


def test_point_validates_inputs():
    with pytest.raises(ValueError, match="lat"):
        aoi_from_point.invoke({"lat": 91.0, "lon": 0.0, "radius_km": 1.0})
    with pytest.raises(ValueError, match="lon"):
        aoi_from_point.invoke({"lat": 0.0, "lon": 181.0, "radius_km": 1.0})
    with pytest.raises(ValueError, match="radius_km"):
        aoi_from_point.invoke({"lat": 0.0, "lon": 0.0, "radius_km": 0.0})


def test_gazetteer_boxes_valid():
    for west, south, east, north in GAZETTEER.values():
        assert -180.0 <= west < east <= 180.0
        assert -90.0 <= south < north <= 90.0
