"""Turn scored runs into CSV files and a console summary.

Two CSVs (gnw-evals shape): a wide ``summary`` for at-a-glance pass rates and a
``detailed`` one with expected-vs-actual for every dimension. The console shows
a per-case table plus overall and per-group pass rates.
"""

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .runner import CaseRun
from .scoring import Scores


@dataclass
class Evaluated:
    """A case run paired with its scores - the unit the report works from."""

    run: CaseRun
    scores: Scores


def _cell(value: object) -> str:
    """Render a value for CSV: None -> "", lists -> "; "-joined."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item) for item in value)
    return str(value)


SUMMARY_FIELDS = [
    "test_id",
    "group",
    "query",
    "overall",
    "passed",
    "tool_score",
    "dataset_score",
    "answer_score",
    "duration_s",
    "error",
]

DETAILED_FIELDS = SUMMARY_FIELDS + [
    "expected_tools",
    "called_tools",
    "forbidden_tools",
    "expected_dataset_ids",
    "matched_dataset_ids",
    "expected_answer",
    "answer",
    "judge_reason",
]


def _row(item: Evaluated) -> dict[str, object]:
    run, scores, case = item.run, item.scores, item.run.case
    return {
        "test_id": case.test_id,
        "group": case.group,
        "query": case.query,
        "overall": scores.overall,
        "passed": scores.passed,
        "tool_score": scores.tool_score,
        "dataset_score": scores.dataset_score,
        "answer_score": scores.answer_score,
        "duration_s": round(run.duration_s, 2),
        "error": run.error,
        "expected_tools": case.expected_tools,
        "called_tools": run.called_tools,
        "forbidden_tools": case.forbidden_tools,
        "expected_dataset_ids": case.expected_dataset_ids,
        "matched_dataset_ids": scores.matched_dataset_ids,
        "expected_answer": case.expected_answer,
        "answer": run.answer,
        "judge_reason": scores.judge_reason,
    }


def write_csvs(items: list[Evaluated], out_dir: Path) -> tuple[Path, Path]:
    """Write the summary and detailed CSVs; return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rows = [_row(item) for item in items]

    paths: list[Path] = []
    for suffix, fields in (("summary", SUMMARY_FIELDS), ("detailed", DETAILED_FIELDS)):
        path = out_dir / f"{stamp}_{suffix}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
            for row in rows:
                writer.writerow([_cell(row[field]) for field in fields])
        paths.append(path)
    return paths[0], paths[1]


def _pass_rate(items: list[Evaluated]) -> str:
    """Pass rate over *scored* cases only.

    Cases that scored nothing (no expectations, or an errored run) are neither
    pass nor fail, so they're excluded from the rate; their count is appended
    so they're still visible.
    """
    scored = [item for item in items if item.scores.overall is not None]
    if not scored:
        return "n/a"
    passed = sum(1 for item in scored if item.scores.passed)
    rate = f"{passed}/{len(scored)} ({passed / len(scored):.0%})"
    unscored = len(items) - len(scored)
    return f"{rate} [dim]+{unscored} not scored[/dim]" if unscored else rate


def _print_details(items: list[Evaluated], console: Console) -> None:
    """Per-case breakdown: the why behind each score, incl. the judge's reason.

    Only dimensions the case actually scored are shown; a dimension with no
    expectation is omitted rather than printed as a confusing blank.
    """
    for item in items:
        run, scores, case = item.run, item.scores, item.run.case
        verdict = "[green]PASS[/green]" if scores.passed else "[red]FAIL[/red]"
        head = "-" if scores.overall is None else f"{scores.overall:.2f} {verdict}"
        console.print(f"\n[bold]{case.test_id}[/bold] [dim]({case.group})[/dim] {head}")
        console.print(f"  [dim]query  :[/dim] {case.query}")
        if run.error:
            console.print(f"  [red]error  :[/red] {run.error}")
        if scores.tool_score is not None:
            console.print(
                f"  [dim]tools  :[/dim] {scores.tool_score}  "
                f"expected {case.expected_tools or '[]'}"
                + (f" forbidden {case.forbidden_tools}" if case.forbidden_tools else "")
                + f"  called {run.called_tools or '[]'}"
            )
        if scores.dataset_score is not None:
            console.print(
                f"  [dim]dataset:[/dim] {scores.dataset_score}  "
                f"expected {case.expected_dataset_ids}  "
                f"matched {scores.matched_dataset_ids or '[]'}"
            )
        if scores.answer_score is not None:
            console.print(
                f"  [dim]answer :[/dim] {scores.answer_score}  "
                f"judge: {scores.judge_reason or '(no reason given)'}"
            )
            console.print(f"  [dim]reply  :[/dim] {run.answer}")


def print_summary(
    items: list[Evaluated], console: Console, verbose: bool = False
) -> None:
    """Print a per-case table and overall + per-group pass rates.

    With ``verbose``, also print a per-case breakdown (expected vs actual for
    each dimension, the agent's reply, and the judge's reasoning).
    """
    if verbose:
        _print_details(items, console)
    table = Table("test_id", "group", "overall", "tools", "dataset", "answer", "error")
    for item in items:
        scores = item.scores
        verdict = "[green]PASS[/green]" if scores.passed else "[red]FAIL[/red]"
        overall = "-" if scores.overall is None else f"{scores.overall:.2f} {verdict}"
        table.add_row(
            item.run.case.test_id,
            item.run.case.group,
            overall,
            _cell(scores.tool_score) or "-",
            _cell(scores.dataset_score) or "-",
            _cell(scores.answer_score) or "-",
            (item.run.error or "")[:40],
        )
    console.print(table)

    console.print(f"\n[bold]Overall:[/bold] {_pass_rate(items)}")
    by_group: dict[str, list[Evaluated]] = defaultdict(list)
    for item in items:
        by_group[item.run.case.group or "(none)"].append(item)
    if len(by_group) > 1:
        for group, group_items in sorted(by_group.items()):
            console.print(f"  [dim]{group}:[/dim] {_pass_rate(group_items)}")
