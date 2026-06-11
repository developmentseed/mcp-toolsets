"""LangChain tools for searching a static C3S/CDS-flavoured dataset catalog."""

from typing import Any

from langchain_core.tools import tool

CATALOG: list[dict[str, Any]] = [
    {
        "id": "reanalysis-era5-single-levels",
        "title": "ERA5 hourly data on single levels from 1940 to present",
        "description": (
            "ERA5 reanalysis providing hourly estimates of atmospheric, land "
            "and oceanic climate variables on single levels, such as 2m "
            "temperature, 10m wind and total precipitation."
        ),
        "keywords": ["reanalysis", "era5", "atmosphere", "hourly", "global"],
        "temporal_coverage": "1940-01-01/present",
    },
    {
        "id": "reanalysis-era5-land",
        "title": "ERA5-Land hourly data from 1950 to present",
        "description": (
            "Enhanced land-surface reanalysis at ~9 km resolution with hourly "
            "variables such as soil moisture, snow cover, surface runoff and "
            "skin temperature."
        ),
        "keywords": ["reanalysis", "era5", "land", "soil", "hourly"],
        "temporal_coverage": "1950-01-01/present",
    },
    {
        "id": "seasonal-original-single-levels",
        "title": "Seasonal forecast daily and subdaily data on single levels",
        "description": (
            "Multi-system seasonal forecasts of atmospheric variables on "
            "single levels from European and international production centres."
        ),
        "keywords": ["seasonal", "forecast", "ensemble", "atmosphere"],
        "temporal_coverage": "1981-01-01/present",
    },
    {
        "id": "projections-cmip6",
        "title": "CMIP6 climate projections",
        "description": (
            "Daily and monthly global climate projections from the Coupled "
            "Model Intercomparison Project Phase 6 across historical and "
            "scenario experiments."
        ),
        "keywords": ["projections", "cmip6", "climate", "scenarios", "models"],
        "temporal_coverage": "1850-01-01/2100-12-31",
    },
    {
        "id": "reanalysis-cerra-single-levels",
        "title": "CERRA sub-daily regional reanalysis data for Europe on single levels",
        "description": (
            "Copernicus European Regional ReAnalysis at 5.5 km resolution "
            "covering Europe, with surface and near-surface variables."
        ),
        "keywords": ["reanalysis", "cerra", "regional", "europe", "high-resolution"],
        "temporal_coverage": "1984-09-01/present",
    },
    {
        "id": "satellite-sea-ice-concentration",
        "title": "Sea ice concentration daily gridded data from satellite observations",
        "description": (
            "Daily sea ice concentration for both hemispheres derived from "
            "passive microwave satellite observations."
        ),
        "keywords": ["satellite", "sea ice", "polar", "ocean", "daily"],
        "temporal_coverage": "1978-10-25/present",
    },
    {
        "id": "insitu-gridded-observations-europe",
        "title": "E-OBS daily gridded meteorological data for Europe",
        "description": (
            "Daily gridded land-only observational dataset over Europe with "
            "temperature, precipitation, sea level pressure and radiation, "
            "based on ECA&D station data."
        ),
        "keywords": ["observations", "e-obs", "europe", "gridded", "stations"],
        "temporal_coverage": "1950-01-01/present",
    },
    {
        "id": "sis-agroclimatic-indicators",
        "title": "Agroclimatic indicators derived from climate projections",
        "description": (
            "Biologically relevant agroclimatic indicators (growing season "
            "length, frost days, warm spells) computed from bias-adjusted "
            "climate projections."
        ),
        "keywords": ["agriculture", "indicators", "projections", "sectoral"],
        "temporal_coverage": "1951-01-01/2099-12-31",
    },
]


def _score(entry: dict[str, Any], terms: list[str]) -> int:
    title = entry["title"].lower()
    description = entry["description"].lower()
    keywords = [keyword.lower() for keyword in entry["keywords"]]
    score = 0
    for term in terms:
        if term in title:
            score += 3
        if any(term in keyword for keyword in keywords):
            score += 2
        if term in description:
            score += 1
    return score


@tool
def search_datasets(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search the catalog for datasets matching a free-text query.

    Scores keyword matches over title, keywords and description; returns the
    best matches (up to `limit`) ordered by relevance. An empty result means
    no dataset matched any query term.
    """
    terms = query.lower().split()
    scored = [(entry, _score(entry, terms)) for entry in CATALOG]
    matches = sorted(
        (item for item in scored if item[1] > 0), key=lambda item: -item[1]
    )
    return [entry for entry, _ in matches[: max(limit, 0)]]


@tool
def get_dataset(dataset_id: str) -> dict[str, Any]:
    """Get the full catalog entry for a dataset by its exact id."""
    for entry in CATALOG:
        if entry["id"] == dataset_id:
            return entry
    known = ", ".join(entry["id"] for entry in CATALOG)
    raise ValueError(f"unknown dataset {dataset_id!r}; known datasets: {known}")


TOOLS = [search_datasets, get_dataset]
