"""Views: MCP resource serving and tool _meta stamping.

Uses synthetic package + tools modules with an on-disk views/ dir, so the
tests never import a real toolset (which come and go).
"""

import sys
import types
from pathlib import Path

import pytest
from langchain_core.tools import tool

from mcp_runtime.fastmcp_output import to_fastmcp
from mcp_runtime.server import build_server
from mcp_runtime.tool_result import ToolResult
from mcp_runtime.views import load_views, view_html, with_view_meta


@tool
def show(text: str) -> ToolResult:
    """Show the text."""
    return ToolResult(message=text)


def toolset_with_views(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    package: str,
    *,
    views: dict[str, str] | None = None,
    bundles: tuple[str, ...] = ("panel",),
    tools: list | None = None,
) -> str:
    """Register a synthetic ``<package>`` + ``<package>.tools`` with a views dir.

    Returns the tools module name. ``bundles`` are the view ids to write HTML
    files for under ``<package>/views/``.
    """
    pkg_dir = tmp_path / package
    (pkg_dir / "views").mkdir(parents=True)
    for view_id in bundles:
        (pkg_dir / "views" / f"{view_id}.html").write_text(f"<h1>{view_id}</h1>")

    pkg = types.ModuleType(package)
    pkg.__file__ = str(pkg_dir / "__init__.py")
    monkeypatch.setitem(sys.modules, package, pkg)

    module_name = f"{package}.tools"
    module = types.ModuleType(module_name)
    module.TOOLS = tools if tools is not None else [show]  # type: ignore[attr-defined]
    module.VIEWS = {"show": "panel"} if views is None else views  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    return module_name


def test_load_views_rejects_bad_export(monkeypatch, tmp_path):
    module = toolset_with_views(monkeypatch, tmp_path, "bad", views={"show": 3})  # type: ignore[dict-item]
    with pytest.raises(RuntimeError, match="VIEWS"):
        load_views(module)


def test_view_html_reads_bundle(monkeypatch, tmp_path):
    module = toolset_with_views(monkeypatch, tmp_path, "reads")
    assert view_html(module, "panel") == "<h1>panel</h1>"


def test_view_html_missing_bundle(monkeypatch, tmp_path):
    module = toolset_with_views(monkeypatch, tmp_path, "nobundle", bundles=())
    with pytest.raises(RuntimeError, match="no bundle"):
        view_html(module, "panel")


def test_with_view_meta_stamps_and_is_pure(monkeypatch, tmp_path):
    module = toolset_with_views(monkeypatch, tmp_path, "stamp")
    original = to_fastmcp(show)
    (stamped,) = with_view_meta("stamp", module, [original], {"show": "panel"})
    assert stamped.meta == {"ui": {"resourceUri": "ui://stamp/panel"}}
    assert original.meta is None  # input untouched


def test_with_view_meta_unknown_tool(monkeypatch, tmp_path):
    module = toolset_with_views(
        monkeypatch, tmp_path, "unknown", views={"ghost": "panel"}
    )
    with pytest.raises(RuntimeError, match="ghost"):
        with_view_meta("unknown", module, [to_fastmcp(show)], {"ghost": "panel"})


async def test_build_server_registers_view_resource(monkeypatch, tmp_path):
    toolset_with_views(monkeypatch, tmp_path, "srv")
    server = build_server("srv", module_name="srv.tools")

    (listed,) = await server.list_tools()
    assert listed.meta == {"ui": {"resourceUri": "ui://srv/panel"}}

    resources = await server.list_resources()
    assert str(resources[0].uri) == "ui://srv/panel"
    # The MCP Apps profile MIME — a plain text/html is rejected by spec hosts.
    assert resources[0].mimeType == "text/html;profile=mcp-app"
    contents = list(await server.read_resource("ui://srv/panel"))
    assert contents[0].content == "<h1>panel</h1>"
