"""Normalize CDS page JSON into markdown corpus files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cds.eqc.discover import dataset_url
from cds.eqc.parse import extract_eqc_prose, parse_metadata, parse_qa_grid

PROSE_HEADING = "## Prose"


def prose_from_markdown(text: str) -> str:
    marker = f"{PROSE_HEADING}\n\n"
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return ""


def write_dataset_markdown(
    *,
    dataset_id: str,
    page_json: dict[str, Any],
    data_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    metadata = parse_metadata(page_json)
    qa = parse_qa_grid(page_json)
    prose = extract_eqc_prose(page_json)

    source_url = dataset_url(dataset_id)
    title = metadata.get("title") or dataset_id
    temporal = ""
    if metadata.get("temporal_start"):
        end = metadata.get("temporal_end") or "present"
        temporal = f"{metadata['temporal_start']} to {end}"

    lines = [
        f"# {title}",
        "",
        f"**Dataset ID:** {dataset_id}",
        f"**URL:** {source_url}",
    ]
    if temporal:
        lines.append(f"**Temporal extent:** {temporal}")
    if metadata.get("provider"):
        lines.append(f"**Provider:** {metadata['provider']}")
    if metadata.get("doi"):
        lines.append(f"**DOI:** {metadata['doi']}")
    lines.append("")

    if prose:
        lines.extend([PROSE_HEADING, "", prose, ""])

    md_path = data_dir / f"{dataset_id}.md"
    data_dir.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "qa_passed": qa["passed"],
        "qa_total": qa["total"],
        "qa_ratio": qa["ratio"],
        "title": title,
        "source_url": source_url,
        "temporal_start": metadata.get("temporal_start"),
        "temporal_end": metadata.get("temporal_end"),
    }
    return md_path, meta
