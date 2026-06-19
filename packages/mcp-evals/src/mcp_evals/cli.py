"""Run the agent eval suite from the command line.

``mcp-evals run`` loads cases (from the configured Google Sheet or a local
``--file``), runs the mcp-agent against each query, scores tool use and answer
quality, writes summary/detailed CSVs, and prints a pass-rate table.
"""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from .config import EvalSettings
from .dataset import EvalCase, fetch_sheet_csv, parse_cases, select
from .report import Evaluated, print_summary, write_csvs
from .runner import run_cases
from .scoring import make_judge, score_run

app = typer.Typer(no_args_is_help=True, help=__doc__)
console = Console()


@app.callback()
def _root() -> None:
    """Keep ``run`` a named subcommand (room for more commands later)."""


def parse_credentials(pairs: list[str] | None) -> dict[str, str] | None:
    """Parse ``Name: value`` credential headers (as curl's ``-H``).

    These ride the MCP transport to credential-needing toolsets; the model
    never sees them.
    """
    if not pairs:
        return None
    headers: dict[str, str] = {}
    for pair in pairs:
        name, sep, value = pair.partition(":")
        if not sep or not name.strip() or not value.strip():
            raise typer.BadParameter(f'expected "Name: value", got {pair!r}')
        headers[name.strip().lower()] = value.strip()
    return headers


def load_cases(
    settings: EvalSettings,
    file: Path | None,
    sheet_id: str | None,
    gid: int | None,
) -> list[EvalCase]:
    """Resolve cases from an explicit file, else the configured sheet."""
    if file is not None:
        return parse_cases(file.read_text(encoding="utf-8"))
    spreadsheet_id = sheet_id or settings.spreadsheet_id
    if not spreadsheet_id:
        raise typer.BadParameter(
            "no eval data source: pass --file, or --sheet-id / set SPREADSHEET_ID."
        )
    return parse_cases(fetch_sheet_csv(spreadsheet_id, gid or settings.spreadsheet_gid))


async def _evaluate(
    cases: list[EvalCase],
    settings: EvalSettings,
    url: str,
    credentials: dict[str, str] | None,
    workers: int,
) -> list[Evaluated]:
    runs = await run_cases(
        cases,
        url=url,
        model=settings.mistral_model,
        api_key=settings.mistral_api_key,
        credentials=credentials,
        workers=workers,
    )
    judge = make_judge(settings.mistral_api_key, settings.judge_model)
    return [Evaluated(run=run, scores=await score_run(run, judge)) for run in runs]


@app.command()
def run(
    url: Annotated[
        str | None,
        typer.Option("--url", help="MCP index or single endpoint. [env MCP_URL]"),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", help="Local CSV of cases instead of the sheet."),
    ] = None,
    sheet_id: Annotated[
        str | None,
        typer.Option("--sheet-id", help="Google Sheet id. [env SPREADSHEET_ID]"),
    ] = None,
    gid: Annotated[
        int | None, typer.Option("--gid", help="Sheet tab gid (default 0).")
    ] = None,
    group: Annotated[
        str | None, typer.Option("--group", help="Only run cases in this group.")
    ] = None,
    sample: Annotated[
        int | None, typer.Option("--sample", help="Cap the number of cases.")
    ] = None,
    workers: Annotated[
        int, typer.Option("--workers", help="Concurrent agent runs.")
    ] = 2,
    credential: Annotated[
        list[str] | None,
        typer.Option(
            "--credential",
            "-c",
            help='Toolset credential as "Header: value" (repeatable), '
            "e.g. -c 'x-cds-token: ...'.",
        ),
    ] = None,
    out: Annotated[
        Path, typer.Option("--out", help="Directory for result CSVs.")
    ] = Path("outputs"),
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Print a per-case breakdown incl. the judge's reasoning.",
        ),
    ] = False,
) -> None:
    """Run the eval suite and write results."""
    try:
        settings = EvalSettings()
    except ValidationError:
        console.print("[red]MISTRAL_API_KEY is not set (environment or .env)[/red]")
        raise typer.Exit(1) from None

    credentials = parse_credentials(credential)
    cases = select(
        load_cases(settings, file, sheet_id, gid), group=group, sample=sample
    )
    if not cases:
        console.print("[yellow]No active cases matched the filters.[/yellow]")
        raise typer.Exit(1)
    for case in cases:
        if not case.has_expectation:
            console.print(
                f"[yellow]{case.test_id}: no expected_* set; it will score nothing."
                "[/yellow]"
            )

    target = url or settings.mcp_url
    console.print(f"Running [bold]{len(cases)}[/bold] case(s) against {target} ...")
    items = asyncio.run(_evaluate(cases, settings, target, credentials, workers))

    print_summary(items, console, verbose=verbose)
    summary_path, detailed_path = write_csvs(items, out)
    console.print(f"\n[dim]Wrote {summary_path} and {detailed_path}[/dim]")
