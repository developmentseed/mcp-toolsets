import pytest

from dataset_search.tools import CATALOG, get_dataset, search_datasets


def test_search_finds_era5():
    results = search_datasets.invoke({"query": "era5"})
    ids = [entry["id"] for entry in results]
    assert "reanalysis-era5-single-levels" in ids
    assert "reanalysis-era5-land" in ids


def test_search_ranks_title_match_first():
    results = search_datasets.invoke({"query": "sea ice"})
    assert results[0]["id"] == "satellite-sea-ice-concentration"


def test_search_respects_limit():
    results = search_datasets.invoke({"query": "reanalysis europe", "limit": 2})
    assert len(results) == 2


def test_search_no_match_returns_empty():
    assert search_datasets.invoke({"query": "zzz-nonexistent"}) == []


def test_search_empty_query_returns_empty():
    assert search_datasets.invoke({"query": ""}) == []


def test_get_dataset_returns_entry():
    entry = get_dataset.invoke({"dataset_id": "projections-cmip6"})
    assert entry["title"] == "CMIP6 climate projections"


def test_get_dataset_unknown_id_lists_known():
    with pytest.raises(ValueError, match="known datasets"):
        get_dataset.invoke({"dataset_id": "nope"})


def test_catalog_entries_complete():
    for entry in CATALOG:
        assert entry["id"] and entry["title"] and entry["description"]
        assert entry["keywords"] and entry["temporal_coverage"]
