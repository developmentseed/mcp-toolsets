"""Run the mcp-agent against eval cases and capture what it did.

This reuses the agent plumbing from ``mcp_agent`` rather than reimplementing
it: :func:`build_agent` discovers the tools behind an MCP URL once, and each
case is one :func:`run_turn` call wrapped in :func:`user_credentials` so
credential-needing toolsets work without the model ever seeing the secret.
"""

import asyncio
import time
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage
from mcp_agent.main import build_agent, run_turn, user_credentials
from pydantic import SecretStr

from .dataset import EvalCase


@dataclass
class ToolCall:
    """A single tool invocation made by the agent during a run."""

    name: str
    args: dict


@dataclass
class CaseRun:
    """The observable result of running one case through the agent."""

    case: EvalCase
    answer: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    duration_s: float = 0.0
    error: str | None = None

    @property
    def called_tools(self) -> list[str]:
        return [call.name for call in self.tool_calls]


def _trajectory(history: list[BaseMessage]) -> list[ToolCall]:
    """Pull every tool call out of a turn's message history.

    Uses the same ``message.tool_calls`` access as ``mcp_agent.main.chat_loop``.
    """
    calls: list[ToolCall] = []
    for message in history:
        for call in getattr(message, "tool_calls", None) or []:
            calls.append(ToolCall(name=call["name"], args=dict(call.get("args", {}))))
    return calls


async def run_case(
    agent: object,
    case: EvalCase,
    credentials: dict[str, str] | None = None,
) -> CaseRun:
    """Run one case as a single-turn conversation and capture the result."""
    started = time.monotonic()
    try:
        with user_credentials(credentials):
            history, _ = await run_turn(agent, [], case.query)
        answer = str(history[-1].content) if history else ""
        return CaseRun(
            case=case,
            answer=answer,
            tool_calls=_trajectory(history),
            duration_s=time.monotonic() - started,
        )
    except Exception as error:  # noqa: BLE001 - one bad case shouldn't abort the run
        return CaseRun(
            case=case,
            duration_s=time.monotonic() - started,
            error=f"{type(error).__name__}: {error}",
        )


async def run_cases(
    cases: list[EvalCase],
    url: str,
    model: str,
    api_key: SecretStr,
    credentials: dict[str, str] | None = None,
    workers: int = 2,
) -> list[CaseRun]:
    """Build the agent once, then run all cases with bounded concurrency.

    Results come back in the input order regardless of completion order.
    """
    agent, _connections, _tools = await build_agent(url, model, api_key)
    semaphore = asyncio.Semaphore(max(1, workers))

    async def guarded(case: EvalCase) -> CaseRun:
        async with semaphore:
            return await run_case(agent, case, credentials)

    return await asyncio.gather(*(guarded(case) for case in cases))
