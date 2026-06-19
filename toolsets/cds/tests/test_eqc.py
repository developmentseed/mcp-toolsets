"""Tests for CDS EQC corpus fetch, parse, search, and MCP tools."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from cds.eqc.discover import discover_build_id, list_catalogue_datasets, next_data_url
from cds.eqc.fetch import sync_corpus
from cds.eqc.normalize import prose_from_markdown, write_dataset_markdown
from cds.eqc.parse import extract_eqc_prose, has_eqc_content, parse_qa_grid
from cds.eqc.sgrep import build_index, data_status, query_index
from cds.tools import TOOLS
from cds.tools.get_dataset_eqc import get_dataset_eqc
from cds.tools.search_eqc import search_eqc

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ERA5_JSON = FIXTURES / "reanalysis-era5-single-levels.json"


@pytest.fixture
def era5_page() -> dict:
    return json.loads(ERA5_JSON.read_text(encoding="utf-8"))


@pytest.fixture
def eqc_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, era5_page: dict):
    data_dir = tmp_path / "data" / "eqc"
    index_dir = tmp_path / "data" / "eqc_index"
    monkeypatch.setenv("EQC_DATA_DIR", str(data_dir))
    monkeypatch.setenv("EQC_INDEX_DIR", str(index_dir))

    raw_dir_path = data_dir / "raw"
    raw_dir_path.mkdir(parents=True)
    dataset_id = "reanalysis-era5-single-levels"
    (raw_dir_path / f"{dataset_id}.json").write_text(
        json.dumps(era5_page, ensure_ascii=False),
        encoding="utf-8",
    )
    write_dataset_markdown(
        dataset_id=dataset_id, page_json=era5_page, data_dir=data_dir
    )

    index = {
        "build_id": "test-build",
        "datasets": [
            {
                "id": dataset_id,
                "title": "ERA5 hourly data on single levels from 1940 to present",
                "has_eqc": True,
                "fetched_at": "2026-01-01T00:00:00+00:00",
                "sha256": "abc",
                "source_url": (
                    "https://cds.climate.copernicus.eu/datasets/"
                    "reanalysis-era5-single-levels?tab=quality_assurance_tab"
                ),
                "qa_passed": 1,
                "qa_total": 1,
                "qa_ratio": 1.0,
            }
        ],
    }
    (data_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    build_index(data_dir=data_dir, index_dir=index_dir)
    return tmp_path


def test_tools_export_includes_eqc() -> None:
    names = {tool.name for tool in TOOLS}
    assert "search_eqc" in names
    assert "get_dataset_eqc" in names


def test_has_eqc_content(era5_page: dict) -> None:
    assert has_eqc_content(era5_page) is True


def test_parse_qa_grid(era5_page: dict) -> None:
    qa = parse_qa_grid(era5_page)
    assert qa["total"] > 0
    assert 0.0 <= qa["ratio"] <= 1.0


def test_extract_eqc_prose(era5_page: dict) -> None:
    prose = extract_eqc_prose(era5_page)
    assert prose
    assert "<span" not in prose
    assert "fitness" in prose.lower() or "quality" in prose.lower()


def test_clean_prose_strips_html() -> None:
    from cds.eqc.clean import clean_prose

    raw = (
        "<span style='color: #777;'>Evaluated on 01/04/2025</span>\n\nHello **world**."
    )
    cleaned = clean_prose(raw)
    assert "<span" not in cleaned
    assert "Evaluated on 01/04/2025" in cleaned
    assert "Hello" in cleaned


def test_write_dataset_markdown_stores_prose(tmp_path: Path, era5_page: dict) -> None:
    data_dir = tmp_path / "eqc"
    md_path, meta = write_dataset_markdown(
        dataset_id="reanalysis-era5-single-levels",
        page_json=era5_page,
        data_dir=data_dir,
    )
    text = md_path.read_text(encoding="utf-8")
    assert "## Prose" in text
    assert "<span" not in text
    assert prose_from_markdown(text)
    assert "quality_assurance_tab" in text
    assert meta["qa_total"] > 0


def test_discover_build_id() -> None:
    html = '<script src="/_next/static/abc123/_buildManifest.js"></script>'
    client = MagicMock()
    request = httpx.Request("GET", "https://cds.climate.copernicus.eu/datasets")
    client.get.return_value = httpx.Response(200, text=html, request=request)
    assert discover_build_id(client) == "abc123"


def test_list_catalogue_datasets() -> None:
    payload = {
        "collections": [
            {"id": "reanalysis-era5-single-levels", "title": "ERA5"},
        ]
    }
    client = MagicMock()
    request = httpx.Request(
        "GET", "https://cds.climate.copernicus.eu/api/catalogue/v1/datasets"
    )
    client.get.return_value = httpx.Response(200, json=payload, request=request)
    items = list_catalogue_datasets(client)
    assert items == [{"id": "reanalysis-era5-single-levels", "title": "ERA5"}]


def test_next_data_url() -> None:
    url = next_data_url("reanalysis-era5-single-levels", "build123")
    assert "build123" in url
    assert "quality_assurance_tab" in url


def test_data_status_ok(eqc_env: Path) -> None:
    ok, detail = data_status()
    assert ok is True
    assert "EQC datasets" in detail


def test_query_index_finds_temperature(eqc_env: Path) -> None:
    results = query_index("hourly temperature reanalysis Europe", k=5)
    assert results
    assert results[0]["dataset_id"] == "reanalysis-era5-single-levels"
    assert results[0]["score"] > 0.08


async def test_search_eqc_tool(eqc_env: Path) -> None:
    results = await search_eqc.ainvoke(
        {"query": "hourly temperature reanalysis Europe", "limit": 5}
    )
    assert isinstance(results, list)
    assert results[0]["dataset_id"] == "reanalysis-era5-single-levels"
    assert "excerpt" in results[0]


async def test_get_dataset_eqc_tool(eqc_env: Path) -> None:
    result = await get_dataset_eqc.ainvoke(
        {"dataset_id": "reanalysis-era5-single-levels"}
    )
    assert result["has_eqc"] is True
    assert result["prose"]
    assert result["qa_total"] > 0


async def test_get_dataset_eqc_missing(eqc_env: Path) -> None:
    result = await get_dataset_eqc.ainvoke({"dataset_id": "no-such-dataset"})
    assert result["error"] == "not_in_corpus"


async def test_search_eqc_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EQC_DATA_DIR", str(tmp_path / "missing" / "eqc"))
    monkeypatch.setenv("EQC_INDEX_DIR", str(tmp_path / "missing" / "eqc_index"))
    results = await search_eqc.ainvoke({"query": "temperature"})
    assert results[0]["error"] == "eqc_corpus_unavailable"


def test_sync_corpus_skips_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data" / "eqc"
    monkeypatch.setenv("EQC_DATA_DIR", str(data_dir))
    monkeypatch.setenv("EQC_INDEX_DIR", str(tmp_path / "data" / "eqc_index"))

    catalogue = [{"id": "reanalysis-era5-single-levels", "title": "ERA5"}]
    page = json.loads(ERA5_JSON.read_text(encoding="utf-8"))

    with (
        patch("cds.eqc.fetch.discover_build_id", return_value="build1"),
        patch("cds.eqc.fetch.list_catalogue_datasets", return_value=catalogue),
        patch("cds.eqc.fetch.fetch_page_json", return_value=page),
    ):
        stats1 = sync_corpus(workers=1, delay_min=0, delay_max=0)
        stats2 = sync_corpus(workers=1, delay_min=0, delay_max=0)

    assert stats1["with_eqc"] == 1
    assert stats2["skipped"] >= 1
