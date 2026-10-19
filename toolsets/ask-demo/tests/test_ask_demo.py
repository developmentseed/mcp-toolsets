import asyncio

import pytest
from mcp.types import ElicitResult
from mcp_runtime.questions import AskUser, answers_context

from ask_demo.tools import TOOLS, download, export, register_webhook, subscribe


def run(tool, arguments, replies=None):
    with answers_context(replies):
        return asyncio.run(tool.ainvoke(arguments))


def accept(key, **content):
    return {key: ElicitResult(action="accept", content=content)}


@pytest.mark.parametrize("tool", TOOLS)
def test_the_first_call_asks(tool):
    arguments = {} if tool is register_webhook else {"dataset": "era5"}
    with pytest.raises(AskUser) as asked:
        run(tool, arguments)
    [(message, schema)] = asked.value.requests.values()
    assert message and schema["required"]


def test_the_answer_picks_the_year():
    result = run(download, {"dataset": "era5"}, accept("which", year=2024))
    assert result == {"message": "Downloaded era5 for 2024."}


def test_the_address_is_told():
    answer = accept("which", year=2024, notify="a@b.c")
    result = run(download, {"dataset": "era5"}, answer)
    assert result == {"message": "Downloaded era5 for 2024. Told a@b.c."}


def test_a_declined_question_downloads_nothing():
    declined = {"which": ElicitResult(action="decline")}
    result = run(download, {"dataset": "era5"}, declined)
    assert result["message"].startswith("No year chosen")


def test_the_schedule_is_read_back():
    answer = accept("schedule", frequency="weekly", start="2026-11-02", digest=False)
    result = run(subscribe, {"dataset": "era5"}, answer)
    assert result == {
        "message": "Subscribed to era5: weekly from 2026-11-02, as every change."
    }


def test_several_variables_are_exported():
    answer = accept("what", variables=["t2m", "tp"], format="zarr")
    result = run(export, {"dataset": "era5"}, answer)
    assert result == {"message": "Exporting t2m, tp of era5 as zarr."}


def test_the_webhook_is_registered():
    answer = accept("where", url="https://example.org/hook", label="ops")
    result = run(register_webhook, {}, answer)
    assert result == {"message": "Webhook ops will POST to https://example.org/hook."}
