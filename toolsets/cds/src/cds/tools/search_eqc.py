"""Semantic search over baked CDS EQC quality-assurance prose."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from cds.eqc.sgrep import data_status, query_index


def _snippet(text: str, max_len: int = 400) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= max_len:
        return one_line
    return one_line[:max_len].rsplit(" ", 1)[0] + "..."


@tool
async def search_eqc(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search CDS quality-assurance (EQC) content by meaning.

    Uses a local semantic index over each dataset's EQC prose. No live CDS
    or LLM calls. Use get_dataset_eqc for the full text of a hit.

    Args:
        query: Natural-language question, e.g. "hourly temperature over Europe
            for renewable energy planning".
        limit: Maximum number of datasets to return (default 10).
    """
    ok, detail = data_status()
    if not ok:
        return [{"error": "eqc_corpus_unavailable", "detail": detail}]

    results = query_index(query, k=limit)
    if not results:
        results = query_index(query, k=limit, threshold=0.0)
    if not results:
        return [{"message": "no_eqc_matches", "query": query}]

    return [
        {
            "dataset_id": r["dataset_id"],
            "score": r["score"],
            "excerpt": _snippet(r["text"]),
            "source_url": r["source_url"],
        }
        for r in results
    ]
