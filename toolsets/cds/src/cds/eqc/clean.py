"""Strip embedded HTML from CDS EQC prose."""

from __future__ import annotations

import trafilatura


def clean_prose(text: str) -> str:
    """Convert HTML-rich EQC markdown to plain markdown."""
    text = text.strip()
    if not text:
        return ""
    cleaned = trafilatura.extract(
        f"<html><body><article>{text}</article></body></html>",
        output_format="markdown",
        include_comments=False,
        include_tables=True,
    )
    return cleaned.strip() if cleaned else text
