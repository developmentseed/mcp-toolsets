"""Fetch CDS EQC page-data JSON into the local corpus."""

from __future__ import annotations

import hashlib
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from cds.eqc.discover import (
    USER_AGENT,
    discover_build_id,
    list_catalogue_datasets,
    next_data_url,
)
from cds.eqc.index import load_index, save_index
from cds.eqc.normalize import write_dataset_markdown
from cds.eqc.parse import has_eqc_content
from cds.eqc.paths import default_data_dir, raw_dir

DEFAULT_DELAY_MIN = 1.0
DEFAULT_DELAY_MAX = 2.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_page_json(
    client: httpx.Client,
    dataset_id: str,
    build_id: str,
) -> dict[str, Any]:
    data_url = next_data_url(dataset_id, build_id)
    response = client.get(data_url)
    response.raise_for_status()
    return response.json()


def _store_raw_json(raw_path: Path, page_json: dict[str, Any]) -> None:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps(page_json, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _process_dataset(
    *,
    dataset_id: str,
    title: str,
    build_id: str,
    data_dir: Path,
    force: bool,
    headers: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    raw_path = raw_dir(data_dir) / f"{dataset_id}.json"
    existing = next(
        (e for e in load_index(data_dir).get("datasets", []) if e.get("id") == dataset_id),
        None,
    )
    if existing and not force and raw_path.exists():
        digest = sha256_file(raw_path)
        if digest == existing.get("sha256"):
            return existing

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=timeout,
        trust_env=True,
    ) as client:
        page_json = fetch_page_json(client, dataset_id, build_id)

    _store_raw_json(raw_path, page_json)
    digest = sha256_file(raw_path)
    fetched_at = datetime.now(UTC).isoformat()
    has_eqc = has_eqc_content(page_json)

    entry: dict[str, Any] = {
        "id": dataset_id,
        "title": title,
        "has_eqc": has_eqc,
        "fetched_at": fetched_at,
        "sha256": digest,
        "source_url": f"https://cds.climate.copernicus.eu/datasets/{dataset_id}?tab=quality_assurance_tab",
        "data_url": next_data_url(dataset_id, build_id),
        "build_id": build_id,
        "bytes": raw_path.stat().st_size,
    }

    if has_eqc:
        md_path, md_meta = write_dataset_markdown(
            dataset_id=dataset_id,
            page_json=page_json,
            data_dir=data_dir,
        )
        entry.update(md_meta)
        entry["markdown_path"] = str(md_path.relative_to(data_dir))
    else:
        md_path = data_dir / f"{dataset_id}.md"
        if md_path.exists():
            md_path.unlink()

    return entry


def sync_corpus(
    *,
    data_dir: Path | None = None,
    limit: int | None = None,
    force: bool = False,
    delay_min: float = DEFAULT_DELAY_MIN,
    delay_max: float = DEFAULT_DELAY_MAX,
    workers: int = 1,
    timeout: float = 120.0,
) -> dict[str, int]:
    """Fetch EQC snapshots for catalogue datasets and refresh the local corpus."""
    data_dir = data_dir or default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    raw_dir(data_dir).mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=timeout,
        trust_env=True,
    ) as client:
        build_id = discover_build_id(client)
        catalogue = list_catalogue_datasets(client)

    if limit is not None:
        catalogue = catalogue[:limit]

    entries_by_id: dict[str, dict[str, Any]] = {
        e["id"]: e for e in load_index(data_dir).get("datasets", []) if e.get("id")
    }
    stats = {"fetched": 0, "skipped": 0, "with_eqc": 0, "errors": 0}

    def run_one(item: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str | None]:
        dataset_id = item["id"]
        try:
            before = entries_by_id.get(dataset_id, {}).get("sha256")
            entry = _process_dataset(
                dataset_id=dataset_id,
                title=item.get("title", ""),
                build_id=build_id,
                data_dir=data_dir,
                force=force,
                headers=headers,
                timeout=timeout,
            )
            if before and before == entry.get("sha256") and not force:
                return dataset_id, None, "skipped"
            return dataset_id, entry, None
        except Exception as exc:  # noqa: BLE001 — collect per-dataset errors
            return dataset_id, None, str(exc)

    items = list(catalogue)
    if workers <= 1:
        for i, item in enumerate(items):
            if i > 0:
                time.sleep(random.uniform(delay_min, delay_max))
            dataset_id, entry, err = run_one(item)
            if err == "skipped":
                stats["skipped"] += 1
            elif err:
                stats["errors"] += 1
            elif entry:
                entries_by_id[dataset_id] = entry
                stats["fetched"] += 1
                if entry.get("has_eqc"):
                    stats["with_eqc"] += 1
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_one, item): item for item in items}
            for future in as_completed(futures):
                dataset_id, entry, err = future.result()
                if err == "skipped":
                    stats["skipped"] += 1
                elif err:
                    stats["errors"] += 1
                elif entry:
                    entries_by_id[dataset_id] = entry
                    stats["fetched"] += 1
                    if entry.get("has_eqc"):
                        stats["with_eqc"] += 1

    datasets = sorted(entries_by_id.values(), key=lambda e: e.get("id", ""))
    save_index(
        {
            "build_id": build_id,
            "updated_at": datetime.now(UTC).isoformat(),
            "datasets": datasets,
        },
        data_dir,
    )
    stats["total_indexed"] = len(datasets)
    stats["eqc_count"] = sum(1 for d in datasets if d.get("has_eqc"))
    return stats
