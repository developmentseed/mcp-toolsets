import asyncio

import pytest
from mcp.types import ElicitResult
from mcp_runtime.questions import AskUser, answers_context

from ask_demo.tools import download


def test_the_first_call_asks_which_year():
    with pytest.raises(AskUser) as asked:
        asyncio.run(download.ainvoke({"dataset": "era5"}))
    message, schema = asked.value.requests["year"]
    assert message == "Which year of era5?"
    assert schema["required"] == ["year"]


def test_the_answer_picks_the_year():
    with answers_context(
        {"year": ElicitResult(action="accept", content={"year": 2024})}
    ):
        result = asyncio.run(download.ainvoke({"dataset": "era5"}))
    assert result == {"message": "Downloaded era5 for 2024."}


def test_a_declined_question_downloads_nothing():
    with answers_context({"year": ElicitResult(action="decline")}):
        result = asyncio.run(download.ainvoke({"dataset": "era5"}))
    assert result["message"].startswith("No year chosen")
