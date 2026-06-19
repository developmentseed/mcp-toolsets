from mcp_evals.dataset import EvalCase
from mcp_evals.runner import CaseRun, ToolCall
from mcp_evals.scoring import (
    Scores,
    score_dataset,
    score_run,
    score_tools,
)


def _run(case: EvalCase, **kwargs) -> CaseRun:
    return CaseRun(case=case, **kwargs)


def test_score_tools_requires_expected_and_forbids_others():
    case = EvalCase(
        test_id="x",
        query="q",
        expected_tools=["search_datasets"],
        forbidden_tools=["submit_request"],
    )
    ok = _run(case, tool_calls=[ToolCall("search_datasets", {})])
    assert score_tools(ok) == 1

    missing = _run(case, tool_calls=[])
    assert score_tools(missing) == 0

    forbidden = _run(
        case,
        tool_calls=[ToolCall("search_datasets", {}), ToolCall("submit_request", {})],
    )
    assert score_tools(forbidden) == 0


def test_score_tools_none_when_no_expectation():
    assert score_tools(_run(EvalCase(test_id="x", query="q"))) is None


def test_score_dataset_matches_in_args_or_answer_any_of():
    case = EvalCase(
        test_id="x",
        query="q",
        expected_dataset_ids=["reanalysis-era5-land", "reanalysis-era5-single-levels"],
    )
    # Match via a tool-call argument.
    via_args = _run(
        case, tool_calls=[ToolCall("get_schema", {"dataset": "reanalysis-era5-land"})]
    )
    score, matched = score_dataset(via_args)
    assert score == 1 and matched == ["reanalysis-era5-land"]

    # Match via the answer text (case-insensitive).
    via_answer = _run(case, answer="Use Reanalysis-ERA5-Single-Levels for that.")
    score, matched = score_dataset(via_answer)
    assert score == 1 and matched == ["reanalysis-era5-single-levels"]

    miss = _run(case, answer="no dataset here")
    assert score_dataset(miss) == (0, [])


def test_score_dataset_none_when_no_expectation():
    assert score_dataset(_run(EvalCase(test_id="x", query="q"))) == (None, [])


def test_scores_rollup_averages_present_only():
    scores = Scores(tool_score=1, dataset_score=0, answer_score=None)
    assert scores.overall == 0.5  # answer None excluded
    assert not scores.passed

    perfect = Scores(tool_score=1, dataset_score=1)
    assert perfect.overall == 1.0 and perfect.passed

    empty = Scores()
    assert empty.overall is None and not empty.passed


class _FakeJudge:
    def __init__(self, score: int, reason: str = "ok"):
        self._result = type("R", (), {"score": score, "reason": reason})()

    async def ainvoke(self, _inputs):
        return self._result


async def test_score_run_uses_judge_for_answer():
    case = EvalCase(
        test_id="x",
        query="q",
        expected_answer="picks era5",
        expected_tools=["search_datasets"],
    )
    run = _run(
        case,
        answer="era5 it is",
        tool_calls=[ToolCall("search_datasets", {})],
    )
    scores = await score_run(run, _FakeJudge(1, "matches"))
    assert scores.answer_score == 1
    assert scores.tool_score == 1
    assert scores.judge_reason == "matches"
    assert scores.overall == 1.0


async def test_score_run_skips_judge_on_error():
    case = EvalCase(test_id="x", query="q", expected_answer="anything")
    run = _run(case, error="boom")
    scores = await score_run(run, _FakeJudge(1))
    assert scores.answer_score is None
    assert scores.overall is None
