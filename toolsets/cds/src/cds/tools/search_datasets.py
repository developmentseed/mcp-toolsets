from typing import Any

import httpx
from langchain_core.tools import tool

from ..settings import settings
from ._errors import transient_error
from ._retry import TRANSIENT_EXC, with_retry


@with_retry
async def _call(query: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    ) as client:
        resp = await client.get(
            f"{settings.cds_catalogue_url}/datasets",
            params={"q": query, "limit": 10},
        )
        if resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code != 200:
            return [{"error": "catalogue_error", "detail": resp.text[:200]}]

        data = resp.json()
        results = (
            data.get("results") or data.get("items") or data.get("collections") or []
        )
        return [
            {"id": item.get("id", ""), "title": item.get("title", "")}
            for item in results
            if item.get("id")
        ]


@tool
async def search_datasets(query: str) -> list[dict[str, Any]]:
    """Search for CDS datasets by keyword.

    Args:
        query: Search term, e.g. "ERA5 temperature" or "sea surface salinity".

    Returns a list of matching datasets, each with 'id' and 'title'.
    Use the 'id' as the dataset argument in get_dataset_schema and submit_request.
    """
    try:
        return await _call(query)
    except TRANSIENT_EXC as exc:
        return [transient_error(str(exc))]
