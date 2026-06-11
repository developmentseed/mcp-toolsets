"""LangChain tools for generating bounding-box GeoJSON areas of interest."""

import math
from typing import Any

from langchain_core.tools import tool

KM_PER_DEGREE_LAT = 110.574
KM_PER_DEGREE_LON_AT_EQUATOR = 111.320

# place -> (west, south, east, north)
GAZETTEER: dict[str, tuple[float, float, float, float]] = {
    "europe": (-25.0, 34.0, 45.0, 72.0),
    "alps": (5.0, 44.0, 16.0, 48.0),
    "mediterranean": (-6.0, 30.0, 37.0, 46.0),
    "uk": (-8.6, 49.9, 1.8, 60.9),
    "germany": (5.9, 47.3, 15.0, 55.1),
    "france": (-5.1, 41.3, 9.6, 51.1),
    "italy": (6.6, 35.5, 18.5, 47.1),
    "scandinavia": (4.0, 54.5, 31.0, 71.5),
    "iberian-peninsula": (-9.5, 36.0, 3.3, 43.8),
    "bologna": (11.23, 44.43, 11.43, 44.56),
    "reading": (-1.05, 51.40, -0.90, 51.50),
}


def _degree_offsets(km: float, latitude: float) -> tuple[float, float]:
    """Convert a distance in km to (dlat, dlon) degrees at a given latitude."""
    dlat = km / KM_PER_DEGREE_LAT
    dlon = km / (KM_PER_DEGREE_LON_AT_EQUATOR * math.cos(math.radians(latitude)))
    return dlat, dlon


def _bbox_feature(
    west: float,
    south: float,
    east: float,
    north: float,
    properties: dict[str, Any],
) -> dict[str, Any]:
    west, east = max(west, -180.0), min(east, 180.0)
    south, north = max(south, -90.0), min(north, 90.0)
    return {
        "type": "Feature",
        "bbox": [west, south, east, north],
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [west, south],
                    [east, south],
                    [east, north],
                    [west, north],
                    [west, south],
                ]
            ],
        },
        "properties": properties,
    }


@tool
def aoi_from_place(place: str, buffer_km: float = 0.0) -> dict[str, Any]:
    """Build a bounding-box GeoJSON area of interest for a named place.

    Looks the place up in a small bundled gazetteer (case-insensitive; spaces
    are treated as hyphens) and optionally expands the box by `buffer_km`
    kilometres on every side. Raises an error listing the known places if the
    place is not in the gazetteer.
    """
    key = place.strip().lower().replace(" ", "-")
    if key not in GAZETTEER:
        known = ", ".join(sorted(GAZETTEER))
        raise ValueError(f"unknown place {place!r}; known places: {known}")
    west, south, east, north = GAZETTEER[key]
    if buffer_km < 0:
        raise ValueError("buffer_km must be >= 0")
    if buffer_km:
        mid_latitude = (south + north) / 2
        dlat, dlon = _degree_offsets(buffer_km, mid_latitude)
        west, south, east, north = west - dlon, south - dlat, east + dlon, north + dlat
    return _bbox_feature(
        west, south, east, north, {"place": key, "buffer_km": buffer_km}
    )


@tool
def aoi_from_point(lat: float, lon: float, radius_km: float) -> dict[str, Any]:
    """Build a bounding-box GeoJSON area of interest around a point.

    The box extends `radius_km` kilometres north/south and east/west from the
    point (clamped to valid coordinate ranges). Latitude must be in [-90, 90],
    longitude in [-180, 180] and the radius positive.
    """
    if not -90.0 <= lat <= 90.0:
        raise ValueError("lat must be in [-90, 90]")
    if not -180.0 <= lon <= 180.0:
        raise ValueError("lon must be in [-180, 180]")
    if radius_km <= 0:
        raise ValueError("radius_km must be > 0")
    dlat, dlon = _degree_offsets(radius_km, lat)
    return _bbox_feature(
        lon - dlon,
        lat - dlat,
        lon + dlon,
        lat + dlat,
        {"lat": lat, "lon": lon, "radius_km": radius_km},
    )


TOOLS = [aoi_from_place, aoi_from_point]
