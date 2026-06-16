import sys
import types

import pytest
from langchain_core.tools import tool
from pydantic import ValidationError

from mcp_runtime.server import (
    RuntimeSettings,
    build_server,
    load_credential_headers,
    load_tools,
    toolset_module_name,
)


@tool
def echo(text: str) -> str:
    """Echo the text back."""
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
    assert toolset_module_name("aoi-generator") == "aoi_generator.tools"


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


async def test_build_server_derives_module_from_toolset_name(monkeypatch):
    tools_module(monkeypatch, "fake_toolset.tools", TOOLS=[echo])
    server = build_server("fake-toolset")
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == {"echo"}
    for tool in tools:
        assert tool.description


async def test_build_server_module_override(monkeypatch):
    name = tools_module(monkeypatch, "custom_tools_module", TOOLS=[echo])
    server = build_server("anything", module_name=name)
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == {"echo"}
