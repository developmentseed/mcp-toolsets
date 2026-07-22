"""Unit tests for stac-explorer — the STAC catalog is mocked, no network."""

from collections.abc import Callable

import httpx
import pytest

from stac_explorer import tools
from stac_explorer.tools import search_collections, show_map

# A tiny fake catalog: two collections, one with a thumbnail + bbox.
FIRE = {
    "id": "modis-fire",
    "title": "MODIS Fire",
    "description": "Active fire and thermal anomalies.",
    "keywords": ["fire", "modis"],
    "extent": {"spatial": {"bbox": [[-180, -90, 180, 90]]}},
    "assets": {"thumbnail": {"href": "https://example.test/fire.png"}},
}
LANDSAT = {
    "id": "landsat-c2-l2",
    "title": "Landsat Collection 2 Level-2",
    "description": "Surface reflectance and temperature.",
    "keywords": ["landsat", "imagery"],
    "extent": {"spatial": {"bbox": [[-10.0, 40.0, 5.0, 55.0]]}},
    "assets": {},
}


def mock_stac(monkeypatch: pytest.MonkeyPatch, handler: Callable[..., httpx.Response]):
    """Route every httpx request the tools make through ``handler``."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(tools.httpx, "AsyncClient", factory)


async def test_search_filters_and_trims(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/collections")
        return httpx.Response(200, json={"collections": [FIRE, LANDSAT]})

    mock_stac(monkeypatch, handler)
    result = await search_collections.ainvoke({"query": "fire"})

    assert result["collections"] == [
        {
            "id": "modis-fire",
            "title": "MODIS Fire",
            "description": "Active fire and thermal anomalies.",
            "thumbnail": "https://example.test/fire.png",
            "bbox": [-180.0, -90.0, 180.0, 90.0],
        }
    ]
    assert "MODIS Fire" in result["message"]


async def test_search_honours_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    many = [{**LANDSAT, "id": f"c{i}"} for i in range(20)]
    mock_stac(monkeypatch, lambda r: httpx.Response(200, json={"collections": many}))
    result = await search_collections.ainvoke({"query": "landsat", "limit": 3})
    assert len(result["collections"]) == 3


async def test_search_no_match(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_stac(monkeypatch, lambda r: httpx.Response(200, json={"collections": [FIRE]}))
    result = await search_collections.ainvoke({"query": "nonesuch"})
    assert result["collections"] == []
    assert "No collections" in result["message"]


async def test_search_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_stac(monkeypatch, lambda r: httpx.Response(500))
    result = await search_collections.ainvoke({"query": "fire"})
    assert result["error"] == "upstream_error"


# A stubbed tiler: mosaic/info -> register -> tilejson, as show_map calls them.
TILE_TEMPLATE = "https://pc.test/tiles/{z}/{x}/{y}?colormap_name=landsat"


def tiler_response(path: str) -> httpx.Response | None:
    if path.endswith("/mosaic/info"):
        return httpx.Response(
            200,
            json={
                "mosaics": [{"cql": [{"op": "=", "args": [{"property": "y"}, 2023]}]}],
                "renderOptions": [{"options": "assets=data&colormap_name=landsat"}],
            },
        )
    if path.endswith("/mosaic/register"):
        return httpx.Response(200, json={"searchid": "abc123"})
    if "/tilejson.json" in path:
        return httpx.Response(200, json={"tiles": [TILE_TEMPLATE]})
    return None


async def test_show_map_includes_tile_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/collections/landsat-c2-l2"):
            return httpx.Response(200, json=LANDSAT)
        return tiler_response(path) or httpx.Response(404)

    mock_stac(monkeypatch, handler)
    result = await show_map.ainvoke({"collection_id": "landsat-c2-l2"})
    assert result["collection"]["bbox"] == [-10.0, 40.0, 5.0, 55.0]
    assert result["tile_url"] == TILE_TEMPLATE
    assert "live data layer" in result["message"]


async def test_show_map_degrades_without_tiles(monkeypatch: pytest.MonkeyPatch) -> None:
    # The collection resolves but the tiler is unavailable — still a valid
    # result, just without a data layer (the map shows the extent only).
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/collections/landsat-c2-l2"):
            return httpx.Response(200, json=LANDSAT)
        return httpx.Response(500)

    mock_stac(monkeypatch, handler)
    result = await show_map.ainvoke({"collection_id": "landsat-c2-l2"})
    assert "tile_url" not in result
    assert result["collection"]["id"] == "landsat-c2-l2"
    assert "extent" in result["message"]


async def test_show_map_tiler_404_string_body(monkeypatch: pytest.MonkeyPatch) -> None:
    # mosaic/info answers 404 with a bare JSON *string* (as PC does for
    # collections without a tiler). show_map must degrade, not raise.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/collections/landsat-c2-l2"):
            return httpx.Response(200, json=LANDSAT)
        return httpx.Response(404, json="Mosaic not found")

    mock_stac(monkeypatch, handler)
    result = await show_map.ainvoke({"collection_id": "landsat-c2-l2"})
    assert "tile_url" not in result
    assert result["collection"]["id"] == "landsat-c2-l2"


async def test_show_map_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_stac(monkeypatch, lambda r: httpx.Response(404))
    result = await show_map.ainvoke({"collection_id": "ghost"})
    assert result["error"] == "not_found"
    assert "ghost" in result["detail"]
