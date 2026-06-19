"""Return EQC content for a single CDS dataset."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from cds.eqc.index import get_dataset_entry
from cds.eqc.parse import extract_eqc_prose, parse_qa_grid
from cds.eqc.paths import default_data_dir, raw_dir
from cds.eqc.sgrep import data_status


def _load_page_json(dataset_id: str, data_dir: Path) -> dict[str, Any] | None:
    raw_path = raw_dir(data_dir) / f"{dataset_id}.json"
    if not raw_path.exists():
        return None
    return json.loads(raw_path.read_text(encoding="utf-8"))


@tool
async def get_dataset_eqc(dataset_id: str) -> dict[str, Any]:
    """Return EQC quality-assurance content for a CDS dataset.

    Reads the baked local corpus (no live CDS calls). Returns the full EQC
    prose and a simple QA pass count.

    Args:
        dataset_id: CDS dataset id, e.g. "reanalysis-era5-single-levels".
    """
    data_dir = default_data_dir()
    ok, detail = data_status()
    if not ok:
        return {"error": "eqc_corpus_unavailable", "detail": detail}

    entry = get_dataset_entry(dataset_id, data_dir)
    if entry is None:
        return {"error": "not_in_corpus", "dataset_id": dataset_id}

    if not entry.get("has_eqc"):
        return {
            "dataset_id": dataset_id,
            "has_eqc": False,
            "title": entry.get("title"),
            "source_url": entry.get("source_url"),
            "message": "Dataset is in the catalogue snapshot but has no EQC tab content.",
        }

    page_json = _load_page_json(dataset_id, data_dir)
    if page_json is None:
        return {"error": "raw_snapshot_missing", "dataset_id": dataset_id}

    qa = parse_qa_grid(page_json)

    return {
        "dataset_id": dataset_id,
        "has_eqc": True,
        "title": entry.get("title"),
        "source_url": entry.get("source_url"),
        "prose": extract_eqc_prose(page_json),
        "qa_passed": qa["passed"],
        "qa_total": qa["total"],
    }
