"""Filesystem locations for the EQC corpus and sgrep index."""

from __future__ import annotations

from pathlib import Path

from cds.settings import Settings

# toolsets/cds — stable regardless of process cwd (e.g. mcp-serve from repo root)
_TOOLSET_ROOT = Path(__file__).resolve().parents[3]


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else _TOOLSET_ROOT / p


def default_data_dir() -> Path:
    return _resolve(Settings().eqc_data_dir)


def default_index_dir() -> Path:
    return _resolve(Settings().eqc_index_dir)


def raw_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "raw"


def index_json_path(data_dir: Path | None = None) -> Path:
    return (data_dir or default_data_dir()) / "index.json"
