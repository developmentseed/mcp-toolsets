from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

from mcp_evals import runner
from mcp_evals.dataset import EvalCase
from mcp_evals.runner import CaseRun, _trajectory, run_case


def test_trajectory_collects_tool_calls_across_messages():
    history = [
        HumanMessage("find era5"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "search_datasets", "args": {"query": "era5"}, "id": "1"}
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "get_dataset_eqc", "args": {"dataset": "era5"}, "id": "2"}
            ],
        ),
        AIMessage(content="done"),
    ]
    calls = _trajectory(history)
    assert [c.name for c in calls] == ["search_datasets", "get_dataset_eqc"]
    assert calls[0].args == {"query": "era5"}


async def test_run_case_captures_answer_and_trajectory(monkeypatch):
    history = [
        HumanMessage("q"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {"a": 1}, "id": "1"}]),
        AIMessage(content="the answer"),
    ]

    async def fake_run_turn(agent, messages, text):
        return history, history[2:]

    monkeypatch.setattr(runner, "run_turn", fake_run_turn)
    result = await run_case(object(), EvalCase(test_id="x", query="q"))
    assert result.answer == "the answer"
    assert result.called_tools == ["t"]
    assert result.error is None


async def test_run_case_records_errors_instead_of_raising(monkeypatch):
    async def boom(agent, messages, text):
        raise RuntimeError("mcp down")

    monkeypatch.setattr(runner, "run_turn", boom)
    result = await run_case(object(), EvalCase(test_id="x", query="q"))
    assert result.answer == ""
    assert result.error is not None and "mcp down" in result.error


def test_called_tools_property():
    run = CaseRun(case=EvalCase(test_id="x", query="q"))
    run.tool_calls = [SimpleNamespace(name="a"), SimpleNamespace(name="b")]  # type: ignore[list-item]
    assert run.called_tools == ["a", "b"]
