import asyncio

import pytest
from mcp.types import ElicitResult
from mcp_runtime.questions import AskUser, answers_context

from ask_demo.tools import download


def test_the_first_call_asks_which_year():
    with pytest.raises(AskUser) as asked:
        asyncio.run(download.ainvoke({"dataset": "era5"}))
    message, schema = asked.value.requests["which"]
    assert message == "Which year of era5?"
    assert schema["required"] == ["year"]


def test_the_answer_picks_the_year():
    with answers_context(
        {"which": ElicitResult(action="accept", content={"year": 2024})}
    ):
        result = asyncio.run(download.ainvoke({"dataset": "era5"}))
    assert result == {"message": "Downloaded era5 for 2024."}


def test_a_declined_question_downloads_nothing():
    with answers_context({"which": ElicitResult(action="decline")}):
        result = asyncio.run(download.ainvoke({"dataset": "era5"}))
    assert result["message"].startswith("No year chosen")


def test_the_address_is_told():
    answer = ElicitResult(action="accept", content={"year": 2024, "notify": "a@b.c"})
    with answers_context({"which": answer}):
        result = asyncio.run(download.ainvoke({"dataset": "era5"}))
    assert result == {"message": "Downloaded era5 for 2024. Told a@b.c."}
