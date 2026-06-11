import pytest
from pydantic import ValidationError

from mcp_runtime.server import (
    RuntimeSettings,
    build_server,
    load_tools,
    toolset_module_name,
)


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


async def test_build_server_exposes_tools():
    server = build_server("dataset-search")
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert names == {"search_datasets", "get_dataset"}
    for tool in tools:
        assert tool.description


async def test_build_server_module_override():
    server = build_server("anything", module_name="aoi_generator.tools")
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == {"aoi_from_place", "aoi_from_point"}
