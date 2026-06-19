from rich.console import Console

from mcp_evals.dataset import EvalCase
from mcp_evals.report import Evaluated, print_summary
from mcp_evals.runner import CaseRun, ToolCall
from mcp_evals.scoring import Scores


def _item() -> Evaluated:
    case = EvalCase(
        test_id="cds-search-001",
        group="cds",
        query="find era5",
        expected_answer="picks era5",
        expected_tools=["search_datasets", "search_eqc"],
    )
    run = CaseRun(
        case=case,
        answer="It is reanalysis-era5-single-levels.",
        tool_calls=[ToolCall("search_datasets", {})],
    )
    scores = Scores(
        tool_score=0,
        answer_score=1,
        judge_reason="Correctly names the dataset.",
    )
    return Evaluated(run=run, scores=scores)


def _render(verbose: bool) -> str:
    console = Console(width=200, record=True)
    print_summary([_item()], console, verbose=verbose)
    return console.export_text()


def test_non_verbose_omits_judge_reason():
    out = _render(verbose=False)
    assert "cds-search-001" in out  # table still renders
    assert "Correctly names the dataset." not in out


def test_verbose_prints_judge_reason_and_trajectory():
    out = _render(verbose=True)
    assert "Correctly names the dataset." in out  # judge reasoning
    assert "search_eqc" in out  # expected-vs-called tools
    assert "reanalysis-era5-single-levels" in out  # the agent's reply


def _scored(test_id: str, scores: Scores) -> Evaluated:
    case = EvalCase(test_id=test_id, query="q")
    return Evaluated(run=CaseRun(case=case), scores=scores)


def test_pass_rate_excludes_unscored_cases():
    items = [
        _scored("pass", Scores(tool_score=1)),  # overall 1.0 -> pass
        _scored("unscored", Scores()),  # no expectations -> overall None
    ]
    console = Console(width=200, record=True)
    print_summary(items, console)
    out = console.export_text()
    # Denominator is the scored case only; the unscored one isn't a failure.
    assert "1/1" in out
    assert "100%" in out
    assert "not scored" in out
