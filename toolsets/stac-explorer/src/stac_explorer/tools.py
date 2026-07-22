"""LangChain tools for stac-explorer.

Two tools that together demonstrate a UI round-trip: ``search_collections``
returns a gallery the user picks from, and picking one drives ``show_map``,
which renders the collection on an interactive map. Both hit a public STAC
catalog (no credentials), so the views only ever receive public data.

The views (``VIEWS`` below) are progressive enhancement — each tool's
``message`` and structured data stand alone in a plain MCP client.
"""

from typing import Any, NotRequired, TypedDict

import httpx
from langchain_core.tools import tool

from mcp_runtime.tool_result import ToolError, ToolResult

# A public, no-auth STAC catalog and its tiler. Only public data is read here;
# the tiler signs the underlying storage itself, so nothing the views render
# needs a credential. For a catalog that *did* need auth, show_map would mint a
# signed tile URL server-side and return it — the token would ride the result,
# never reach the iframe.
STAC_ROOT = "https://planetarycomputer.microsoft.com/api/stac/v1"
DATA_ROOT = "https://planetarycomputer.microsoft.com/api/data/v1"
TIMEOUT = httpx.Timeout(30.0)


class Collection(TypedDict):
    """One STAC collection, trimmed to what a view needs."""

    id: str
    title: str
    description: str
    thumbnail: NotRequired[str]
    bbox: NotRequired[list[float]]


class SearchCollectionsResult(ToolResult):
    """Collections whose id/title/description/keywords match the query."""

    collections: NotRequired[list[Collection]]


class ShowMapResult(ToolResult):
    """A single collection positioned for display on a map."""

    collection: NotRequired[Collection]
    tile_url: NotRequired[str]


def _first_bbox(extent: dict[str, Any]) -> list[float] | None:
    """The overall spatial bbox ``[w, s, e, n]`` from a STAC extent, if present."""
    boxes = (extent.get("spatial") or {}).get("bbox") or []
    if boxes and isinstance(boxes[0], list) and len(boxes[0]) >= 4:
        return [float(v) for v in boxes[0][:4]]
    return None


def _thumbnail(assets: dict[str, Any]) -> str | None:
    """A collection's thumbnail asset href, if it advertises one."""
    thumb = assets.get("thumbnail") or assets.get("rendered_preview") or {}
    href = thumb.get("href")
    return href if isinstance(href, str) else None


def _to_collection(raw: dict[str, Any]) -> Collection:
    """Trim a raw STAC collection to the fields the views consume."""
    collection: Collection = {
        "id": str(raw.get("id", "")),
        "title": str(raw.get("title") or raw.get("id", "")),
        "description": str(raw.get("description") or ""),
    }
    if thumb := _thumbnail(raw.get("assets") or {}):
        collection["thumbnail"] = thumb
    if bbox := _first_bbox(raw.get("extent") or {}):
        collection["bbox"] = bbox
    return collection


def _matches(raw: dict[str, Any], query: str) -> bool:
    """Whether a collection matches a free-text query (case-insensitive)."""
    haystack = " ".join(
        [
            str(raw.get("id", "")),
            str(raw.get("title") or ""),
            str(raw.get("description") or ""),
            " ".join(raw.get("keywords") or []),
        ]
    ).lower()
    return all(term in haystack for term in query.lower().split())


@tool
async def search_collections(
    query: str, limit: int = 8
) -> SearchCollectionsResult | ToolError:
    """Search the STAC catalog for collections matching a free-text query.

    Returns matching collections (id, title, description, thumbnail, bbox). The
    caller can then show one on a map with ``show_map``.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{STAC_ROOT}/collections")
            response.raise_for_status()
            raw_collections = response.json().get("collections", [])
    except httpx.HTTPError as error:
        return ToolError(error="upstream_error", detail=f"STAC request failed: {error}")

    matched = [_to_collection(raw) for raw in raw_collections if _matches(raw, query)]
    matched = matched[:limit]
    if not matched:
        return SearchCollectionsResult(
            message=f"No collections matched {query!r}.", collections=[]
        )
    names = ", ".join(collection["title"] for collection in matched)
    return SearchCollectionsResult(
        message=f"Found {len(matched)} collection(s) matching {query!r}: {names}.",
        collections=matched,
    )


def _as_filter(cql: Any) -> Any:
    """Coerce a mosaic's CQL (a list of expressions) into one CQL2 object."""
    if isinstance(cql, list):
        return cql[0] if len(cql) == 1 else {"op": "and", "args": cql}
    return cql


async def _mosaic_tile_url(client: httpx.AsyncClient, collection_id: str) -> str | None:
    """Best-effort XYZ tile template for a collection's default mosaic + render.

    Uses the catalog's own defaults (which assets, which colormap) rather than
    hardcoding per dataset: ask ``mosaic/info`` for the default mosaic and
    render options, register the mosaic to get a search id, then read its
    tilejson. Returns ``None`` whenever the catalog can't produce one — many
    collections (e.g. gridded climate data) have no mosaic tiler and answer
    ``mosaic/info`` with 404 — so the map falls back to the extent and a tiler
    hiccup never fails the tool. Best-effort by contract: it must not raise.
    """
    try:
        info = await _get_json(
            client, f"{DATA_ROOT}/mosaic/info", params={"collection": collection_id}
        )
        mosaics = info.get("mosaics") or [] if isinstance(info, dict) else []
        renders = info.get("renderOptions") or [] if isinstance(info, dict) else []
        if not mosaics or not renders:
            return None
        registered = await client.post(
            f"{DATA_ROOT}/mosaic/register",
            json={
                "filter-lang": "cql2-json",
                "filter": _as_filter(mosaics[0].get("cql")),
                "collections": [collection_id],
            },
        )
        if not registered.is_success:
            return None
        search_id = registered.json().get("searchid")
        if not search_id:
            return None
        options = renders[0].get("options") or ""
        params = dict(pair.split("=", 1) for pair in options.split("&") if "=" in pair)
        params["collection"] = collection_id
        tilejson = await _get_json(
            client, f"{DATA_ROOT}/mosaic/{search_id}/tilejson.json", params=params
        )
        tiles = tilejson.get("tiles") or [] if isinstance(tilejson, dict) else []
        return tiles[0] if tiles else None
    except (httpx.HTTPError, ValueError, AttributeError, TypeError, KeyError):
        return None


async def _get_json(client: httpx.AsyncClient, url: str, **kwargs: Any) -> Any:
    """GET and parse JSON, returning ``None`` on any non-2xx (e.g. a 404 whose
    body is a bare string, which would otherwise break attribute access)."""
    response = await client.get(url, **kwargs)
    return response.json() if response.is_success else None


@tool
async def show_map(collection_id: str) -> ShowMapResult | ToolError:
    """Show a single STAC collection on an interactive map, by its id.

    Fetches the collection, positions it by its spatial extent, and (when the
    catalog's tiler can render it) includes an XYZ tile URL of the actual data
    for the map view to overlay.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{STAC_ROOT}/collections/{collection_id}")
            if response.status_code == 404:
                return ToolError(
                    error="not_found",
                    detail=f"No collection with id {collection_id!r}. "
                    "Use search_collections to find valid ids.",
                )
            response.raise_for_status()
            raw = response.json()
            tile_url = await _mosaic_tile_url(client, collection_id)
    except httpx.HTTPError as error:
        return ToolError(error="upstream_error", detail=f"STAC request failed: {error}")

    collection = _to_collection(raw)
    layer = "with a live data layer" if tile_url else "showing its extent"
    result = ShowMapResult(
        message=f"Showing {collection['title']} on the map ({layer}).",
        collection=collection,
    )
    if tile_url:
        result["tile_url"] = tile_url
    return result


TOOLS = [search_collections, show_map]

VIEWS = {
    "search_collections": "collection-picker",
    "show_map": "map",
}
