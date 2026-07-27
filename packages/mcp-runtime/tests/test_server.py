import sys
import types

import pytest
from langchain_core.tools import tool
from pydantic import ValidationError

from mcp_runtime.server import (
    RuntimeSettings,
    build_server,
    credential_instructions,
    load_credential_headers,
    load_tools,
    toolset_module_name,
)
from mcp_runtime.tool_result import ToolResult


@tool
def echo(text: str) -> ToolResult:
    """Echo the text back."""
    return ToolResult(message=text)


@tool
def bare_echo(text: str) -> str:
    """Echo the text back without following the ToolResult contract."""
    return text


def tools_module(monkeypatch, name: str, **attrs) -> str:
    """Register a synthetic tools module, so tests don't depend on which
    real toolsets exist in the repo."""
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return name


def test_toolset_module_name():
    assert toolset_module_name("dataset-search") == "dataset_search.tools"
    assert toolset_module_name("hello-world") == "hello_world.tools"


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("TOOLSET", "dataset-search")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9000")
    settings = RuntimeSettings()
    assert settings.toolset == "dataset-search"
    assert settings.toolset_module is None
    assert str(settings.host) == "0.0.0.0"
    assert settings.port == 9000


def test_settings_require_toolset(monkeypatch):
    monkeypatch.delenv("TOOLSET", raising=False)
    with pytest.raises(ValidationError):
        RuntimeSettings()


def test_settings_reject_bad_values(monkeypatch):
    monkeypatch.setenv("TOOLSET", "dataset-search")
    monkeypatch.setenv("HOST", "not-an-ip")
    with pytest.raises(ValidationError):
        RuntimeSettings()
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "70000")
    with pytest.raises(ValidationError):
        RuntimeSettings()


def test_load_tools_missing_module():
    with pytest.raises(ModuleNotFoundError):
        load_tools("no_such_toolset.tools")


def test_load_tools_missing_export():
    with pytest.raises(RuntimeError, match="non-empty TOOLS"):
        load_tools("mcp_runtime.server")


def test_load_credential_headers(monkeypatch):
    declaring = tools_module(
        monkeypatch, "declaring_tools", TOOLS=[echo], CREDENTIAL_HEADERS=["X-Fake"]
    )
    bare = tools_module(monkeypatch, "bare_tools", TOOLS=[echo])
    assert load_credential_headers(declaring) == ["x-fake"]
    assert load_credential_headers(bare) == []


def test_load_credential_headers_rejects_bad_export(monkeypatch):
    bad = tools_module(monkeypatch, "bad_tools", CREDENTIAL_HEADERS="x-fake")
    with pytest.raises(RuntimeError, match="CREDENTIAL_HEADERS"):
        load_credential_headers(bad)


def test_credential_instructions():
    assert credential_instructions([]) is None
    text = credential_instructions(["x-cds-token"])
    assert text is not None
    # Names the header and steers the model away from asking for it.
    assert "``x-cds-token``" in text
    assert "do not ask the user" in text


async def test_build_server_sets_credential_instructions(monkeypatch):
    tools_module(
        monkeypatch, "creds_toolset.tools", TOOLS=[echo], CREDENTIAL_HEADERS=["X-Key"]
    )
    server = build_server("creds-toolset")
    assert server.instructions is not None
    assert "``x-key``" in server.instructions


async def test_build_server_no_instructions_without_credentials(monkeypatch):
    tools_module(monkeypatch, "plain_toolset.tools", TOOLS=[echo])
    server = build_server("plain-toolset")
    assert server.instructions is None


async def test_build_server_derives_module_from_toolset_name(monkeypatch):
    tools_module(monkeypatch, "fake_toolset.tools", TOOLS=[echo])
    server = build_server("fake-toolset")
    tools = await server.list_tools()
    assert {t.name for t in tools} == {"echo"}
    for t in tools:
        assert t.description


async def test_build_server_module_override(monkeypatch):
    name = tools_module(monkeypatch, "custom_tools_module", TOOLS=[echo])
    server = build_server("anything", module_name=name)
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == {"echo"}


async def test_build_server_advertises_output_schema(monkeypatch):
    tools_module(monkeypatch, "schema_toolset.tools", TOOLS=[echo])
    server = build_server("schema-toolset")
    (listed,) = await server.list_tools()
    assert listed.outputSchema is not None
    assert "message" in listed.outputSchema["required"]


def test_build_server_rejects_non_contract_tool(monkeypatch):
    tools_module(monkeypatch, "loose_toolset.tools", TOOLS=[bare_echo])
    with pytest.raises(RuntimeError, match="bare_echo"):
        build_server("loose-toolset")
