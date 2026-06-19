"""Score a case run on each dimension and roll the scores up.

Each dimension is binary (1/0) or ``None`` when the case sets no expectation
for it. The overall score is the mean of the present scores, so a case is
graded only on the dimensions its author filled in (gnw-evals' present-only
averaging). Two dimensions are deterministic (tool use, dataset id); answer
quality is graded by a Mistral judge.
"""

import json
from dataclasses import dataclass

from langchain_core.prompts import ChatPromptTemplate
from langchain_mistralai import ChatMistralAI
from pydantic import BaseModel, Field, SecretStr

from .config import PASS_THRESHOLD
from .runner import CaseRun

JUDGE_SYSTEM = (
    "You grade an AI assistant's answer against acceptance criteria. "
    "The criteria describe what a correct answer must convey, not exact "
    "wording. Score 1 if the answer satisfies the criteria (semantically), "
    "else 0. Be strict about factual claims but lenient about phrasing."
)
JUDGE_HUMAN = (
    "User question:\n{query}\n\n"
    "Acceptance criteria:\n{expected}\n\n"
    "Assistant answer:\n{answer}\n\n"
    "Does the answer satisfy the criteria?"
)


class JudgeResult(BaseModel):
    """Structured output from the answer-quality judge."""

    score: int = Field(ge=0, le=1)
    reason: str = ""


@dataclass
class Scores:
    """Per-dimension scores plus the roll-up for one case run."""

    tool_score: int | None = None
    dataset_score: int | None = None
    answer_score: int | None = None
    judge_reason: str = ""
    matched_dataset_ids: list[str] | None = None

    @property
    def present(self) -> list[int]:
        return [
            score
            for score in (self.tool_score, self.dataset_score, self.answer_score)
            if score is not None
        ]

    @property
    def overall(self) -> float | None:
        scores = self.present
        return round(sum(scores) / len(scores), 2) if scores else None

    @property
    def passed(self) -> bool:
        overall = self.overall
        return overall is not None and overall >= PASS_THRESHOLD


def score_tools(run: CaseRun) -> int | None:
    """1 if every expected tool was called and no forbidden tool was."""
    case = run.case
    if not case.expected_tools and not case.forbidden_tools:
        return None
    called = set(run.called_tools)
    expected_ok = set(case.expected_tools) <= called
    forbidden_ok = not (set(case.forbidden_tools) & called)
    return int(expected_ok and forbidden_ok)


def _haystack(run: CaseRun) -> str:
    """Everything an expected dataset id could plausibly appear in, lowercased."""
    parts = [run.answer]
    for call in run.tool_calls:
        parts.append(json.dumps(call.args, default=str))
    return " ".join(parts).lower()


def score_dataset(run: CaseRun) -> tuple[int | None, list[str]]:
    """1 if any expected dataset id surfaced in tool args or the answer.

    Returns the score and which ids matched (for the detailed report).
    """
    expected = run.case.expected_dataset_ids
    if not expected:
        return None, []
    haystack = _haystack(run)
    matched = [ds for ds in expected if ds.lower() in haystack]
    return int(bool(matched)), matched


def make_judge(api_key: SecretStr, model: str):
    """Build the answer-quality judge: a Mistral chat model with structured output."""
    llm = ChatMistralAI(model_name=model, api_key=api_key, temperature=0)
    return ChatPromptTemplate.from_messages(
        [("system", JUDGE_SYSTEM), ("human", JUDGE_HUMAN)]
    ) | llm.with_structured_output(JudgeResult)


async def score_answer(judge: object, run: CaseRun) -> tuple[int | None, str]:
    """Grade the final answer against the acceptance criteria, if any."""
    expected = run.case.expected_answer
    if not expected:
        return None, ""
    result = await judge.ainvoke(  # type: ignore[attr-defined]
        {"query": run.case.query, "expected": expected, "answer": run.answer}
    )
    return int(result.score), result.reason


async def score_run(run: CaseRun, judge: object | None) -> Scores:
    """Score every dimension of one case run.

    A run that errored, or an answer dimension with no judge available, simply
    leaves that dimension ``None`` so it drops out of the average.
    """
    dataset_score, matched = score_dataset(run)
    answer_score: int | None = None
    reason = ""
    if judge is not None and run.error is None:
        answer_score, reason = await score_answer(judge, run)
    return Scores(
        tool_score=score_tools(run),
        dataset_score=dataset_score,
        answer_score=answer_score,
        judge_reason=reason,
        matched_dataset_ids=matched,
    )
