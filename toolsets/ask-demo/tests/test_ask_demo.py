import asyncio

import pytest
from mcp_runtime.questions import Asked, answered

from ask_demo.tools import TOOLS, download, export, register_webhook, subscribe


def run(tool, arguments, answer=...):
    if answer is ...:
        return asyncio.run(tool.ainvoke(arguments))
    with answered(answer):
        return asyncio.run(tool.ainvoke(arguments))


@pytest.mark.parametrize("tool", TOOLS)
def test_the_first_call_asks(tool):
    arguments = {} if tool is register_webhook else {"dataset": "era5"}
    with pytest.raises(Asked) as asked:
        run(tool, arguments)
    assert asked.value.message and asked.value.schema["required"]


def test_the_answer_picks_the_year():
    result = run(download, {"dataset": "era5"}, {"year": 2024})
    assert result == {"message": "Downloaded era5 for 2024."}


def test_the_address_is_told():
    result = run(download, {"dataset": "era5"}, {"year": 2024, "notify": "a@b.c"})
    assert result == {"message": "Downloaded era5 for 2024. Told a@b.c."}


def test_a_declined_question_downloads_nothing():
    result = run(download, {"dataset": "era5"}, None)
    assert result["message"].startswith("No year chosen")


def test_the_schedule_is_read_back():
    answer = {"frequency": "weekly", "start": "2026-11-02", "digest": False}
    result = run(subscribe, {"dataset": "era5"}, answer)
    assert result == {
        "message": "Subscribed to era5: weekly from 2026-11-02, as every change."
    }


def test_several_variables_are_exported():
    answer = {"variables": ["t2m", "tp"], "format": "zarr"}
    result = run(export, {"dataset": "era5"}, answer)
    assert result == {"message": "Exporting t2m, tp of era5 as zarr."}


def test_the_webhook_is_registered():
    answer = {"url": "https://example.org/hook", "label": "ops"}
    result = run(register_webhook, {}, answer)
    assert result == {"message": "Webhook ops will POST to https://example.org/hook."}
