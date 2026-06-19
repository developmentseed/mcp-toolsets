"""Discover CDS dataset IDs and the Next.js build id for page-data fetches."""

from __future__ import annotations

import re
from typing import Any

import httpx

from cds.settings import settings

CDS_BASE = "https://cds.climate.copernicus.eu"
QA_TAB = "quality_assurance_tab"
USER_AGENT = "cds-eqc/0.1 (+https://github.com/copernicus; EQC corpus fetch)"

_BUILD_ID_RE = re.compile(r"/_next/static/([^/]+)/_buildManifest\.js")


def dataset_url(dataset_id: str) -> str:
    return f"{CDS_BASE}/datasets/{dataset_id}?tab={QA_TAB}"


def next_data_url(dataset_id: str, build_id: str) -> str:
    return (
        f"{CDS_BASE}/_next/data/{build_id}/en/datasets/{dataset_id}.json"
        f"?tab={QA_TAB}"
    )


def discover_build_id(client: httpx.Client) -> str:
    response = client.get(f"{CDS_BASE}/datasets")
    response.raise_for_status()
    match = _BUILD_ID_RE.search(response.text)
    if not match:
        raise RuntimeError("Could not discover Next.js build id from CDS datasets page")
    return match.group(1)


def list_catalogue_datasets(
    client: httpx.Client | None = None,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return STAC catalogue collections as {id, title} dicts."""
    own_client = client is None
    if own_client:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=120.0,
            follow_redirects=True,
        )
    assert client is not None
    try:
        response = client.get(
            f"{settings.cds_catalogue_url}/datasets",
            params={"limit": limit},
        )
        response.raise_for_status()
        data = response.json()
        collections = data.get("collections") or data.get("results") or []
        return [
            {"id": item["id"], "title": item.get("title", "")}
            for item in collections
            if item.get("id")
        ]
    finally:
        if own_client:
            client.close()
