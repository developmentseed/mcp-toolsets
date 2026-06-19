"""Read and write the EQC corpus index.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cds.eqc.paths import index_json_path


def load_index(data_dir: Path | None = None) -> dict[str, Any]:
    path = index_json_path(data_dir)
    if not path.exists():
        return {"datasets": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_index(data: dict[str, Any], data_dir: Path | None = None) -> Path:
    path = index_json_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def get_dataset_entry(
    dataset_id: str, data_dir: Path | None = None
) -> dict[str, Any] | None:
    for entry in load_index(data_dir).get("datasets", []):
        if entry.get("id") == dataset_id:
            return entry
    return None


def list_eqc_datasets(data_dir: Path | None = None) -> list[dict[str, Any]]:
    return [d for d in load_index(data_dir).get("datasets", []) if d.get("has_eqc")]
