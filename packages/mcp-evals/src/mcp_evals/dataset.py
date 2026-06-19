"""Eval cases and where they come from.

Cases live in a single Google Sheet tab (or a local CSV with the same columns).
The sheet is read with zero auth via its CSV export URL, so it just needs to be
shared "anyone with the link can view". The same loader handles a local file,
which is handy for tests and offline runs.
"""

import csv
import io
from collections.abc import Iterable

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

CSV_EXPORT_URL = (
    "https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    "/export?format=csv&gid={gid}"
)

# Authors fill in only the dimensions they care about per row, so an empty
# string in any expected column means "don't score this dimension".
_SKIP_STATUS = "skip"


def _split(value: str, sep: str) -> list[str]:
    """Split a delimited cell into trimmed, non-empty items."""
    return [item.strip() for item in value.split(sep) if item.strip()]


class EvalCase(BaseModel):
    """One single-turn evaluation case.

    Unknown columns are kept (``extra="allow"``) so collaborators can add
    metadata (priority, author, ticket link) to the sheet without code changes.
    """

    model_config = ConfigDict(extra="allow")

    test_id: str
    query: str
    group: str = ""
    expected_answer: str = ""
    expected_dataset_ids: list[str] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    status: str = ""
    notes: str = ""

    @field_validator("expected_dataset_ids", mode="before")
    @classmethod
    def _split_dataset_ids(cls, value: object) -> object:
        # Comma-separated: one or more acceptable ids (any-of).
        return _split(value, ",") if isinstance(value, str) else value

    @field_validator("expected_tools", "forbidden_tools", mode="before")
    @classmethod
    def _split_tools(cls, value: object) -> object:
        # Semicolon-separated so tool names may contain commas if ever needed.
        return _split(value, ";") if isinstance(value, str) else value

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @property
    def is_active(self) -> bool:
        return self.status != _SKIP_STATUS

    @property
    def has_expectation(self) -> bool:
        """Whether the case scores anything at all."""
        return bool(
            self.expected_answer or self.expected_dataset_ids or self.expected_tools
        )


def parse_cases(text: str) -> list[EvalCase]:
    """Parse CSV text into cases. Header names map directly to columns."""
    reader = csv.DictReader(io.StringIO(text))
    cases: list[EvalCase] = []
    for row in reader:
        # csv.DictReader yields None keys for ragged rows; drop them and treat
        # missing/None values as empty strings so validators see clean input.
        clean = {k: (v or "") for k, v in row.items() if k}
        if not (clean.get("test_id") or clean.get("query")):
            continue  # blank spacer row
        cases.append(EvalCase.model_validate(clean))
    return cases


def fetch_sheet_csv(spreadsheet_id: str, gid: int = 0) -> str:
    """Download a sheet tab as CSV via its public export URL."""
    url = CSV_EXPORT_URL.format(spreadsheet_id=spreadsheet_id, gid=gid)
    response = httpx.get(url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    return response.text


def select(
    cases: Iterable[EvalCase],
    group: str | None = None,
    sample: int | None = None,
) -> list[EvalCase]:
    """Apply the standard filters: drop skipped, optional group, optional cap.

    Only ``status=skip`` drops a whole row. A row missing some ``expected_*``
    is kept; the dimensions it doesn't specify are simply not scored (see
    :class:`~mcp_evals.scoring.Scores`), not failed.
    """
    selected = [case for case in cases if case.is_active]
    if group:
        selected = [case for case in selected if case.group == group]
    if sample is not None:
        selected = selected[:sample]
    return selected
