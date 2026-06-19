"""Parse EQC content from CDS Next.js page-data JSON."""

from __future__ import annotations

from typing import Any

from cds.eqc.clean import clean_prose


def _aside_blocks(page_json: dict[str, Any]) -> list[dict]:
    layout = page_json.get("pageProps", {}).get("layout", {})
    return layout.get("body", {}).get("aside", {}).get("blocks", [])


def _main_sections(page_json: dict[str, Any]) -> list[dict]:
    layout = page_json.get("pageProps", {}).get("layout", {})
    return layout.get("body", {}).get("main", {}).get("sections", [])


def has_eqc_content(page_json: dict[str, Any]) -> bool:
    aside = _aside_blocks(page_json)
    sections = _main_sections(page_json)
    has_section = any(b.get("id") == "quality_assurance_section" for b in aside)
    qa_tab = next((s for s in sections if s.get("id") == "quality_assurance_tab"), None)
    has_tab = qa_tab is not None and bool(qa_tab.get("blocks"))
    return has_section and has_tab


def _walk_checkitems(blocks: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for block in blocks:
        if block.get("type") == "checkitem":
            rows.append(block)
            rows.extend(_walk_checkitems(block.get("blocks") or []))
    return rows


def parse_qa_grid(page_json: dict[str, Any]) -> dict[str, Any]:
    aside_blocks = _aside_blocks(page_json)
    qa_section = next(
        (b for b in aside_blocks if b.get("id") == "quality_assurance_section"),
        None,
    )
    if qa_section is None:
        raise ValueError("quality_assurance_section not found in snapshot")

    items = _walk_checkitems(qa_section.get("blocks") or [])
    passed = sum(1 for item in items if item.get("status") == "OK")
    total = len(items)
    return {
        "passed": passed,
        "total": total,
        "ratio": passed / total if total else 0.0,
    }


def parse_metadata(page_json: dict[str, Any]) -> dict[str, Any]:
    dataset = page_json.get("pageProps", {}).get("dataset") or {}

    doi = dataset.get("sci:doi") or dataset.get("doi")
    provider = None
    providers = dataset.get("providers") or []
    if providers:
        provider = providers[0].get("name")

    temporal = dataset.get("extent", {}).get("temporal", {}).get("interval", [[]])
    interval = temporal[0] if temporal else []
    temporal_start = interval[0][:10] if interval and interval[0] else None
    temporal_end = interval[1][:10] if len(interval) > 1 and interval[1] else None

    return {
        "title": dataset.get("title"),
        "provider": provider,
        "doi": doi,
        "temporal_start": temporal_start,
        "temporal_end": temporal_end,
        "license": dataset.get("license"),
    }


def _collect_markdown(blocks: list[dict]) -> list[str]:
    parts: list[str] = []
    for block in blocks:
        btype = block.get("type")
        if btype in ("markdown", "thumb-markdown") and block.get("content"):
            parts.append(block["content"].strip())
        nested = block.get("blocks") or []
        if nested:
            parts.extend(_collect_markdown(nested))
    return parts


def extract_eqc_prose(page_json: dict[str, Any]) -> str:
    sections = _main_sections(page_json)
    qa = next((s for s in sections if s.get("id") == "quality_assurance_tab"), None)
    if qa is None:
        return ""
    raw = "\n\n".join(_collect_markdown(qa.get("blocks") or []))
    return clean_prose(raw)
