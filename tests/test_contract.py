"""Contract test: every directory under toolsets/ must export valid TOOLS.

Doubles as a per-toolset import smoke test and enforces non-empty
descriptions (docstrings become the MCP schema, so they are part of the
contract) and the ToolResult return contract (annotations become the MCP
output schema, so every tool in every toolset must convert cleanly).

The sweep itself is a *consumer* concern: mcp-toolsets-runtime ships the gates
it applies (``to_fastmcp``, ``load_credential_headers``, and ``build_server``
behind them) but not the walk over this repo's toolsets/, which it has no way
to locate.
"""

import ast
import importlib
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from langchain_core.tools import BaseTool

from mcp_runtime.fastmcp_output import to_fastmcp
from mcp_runtime.server import load_credential_headers

TOOLSETS_DIR = Path(__file__).resolve().parents[1] / "toolsets"
TOOLSET_NAMES = sorted(
    path.name for path in TOOLSETS_DIR.iterdir() if (path / "pyproject.toml").is_file()
)


def test_toolsets_discovered():
    assert TOOLSET_NAMES


@pytest.mark.parametrize("toolset", TOOLSET_NAMES)
def test_toolset_contract(toolset):
    module_name = toolset.replace("-", "_") + ".tools"
    module = importlib.import_module(module_name)
    load_credential_headers(module_name)  # validates the optional export's shape
    tools = module.TOOLS
    assert isinstance(tools, list) and tools, f"{toolset}: TOOLS must be non-empty"
    for tool in tools:
        assert isinstance(tool, BaseTool), f"{toolset}: {tool!r} is not a BaseTool"
        assert tool.description and tool.description.strip(), (
            f"{toolset}: tool {tool.name!r} needs a non-empty docstring"
        )
        # The same ToolResult gate build_server applies at startup.
        converted = to_fastmcp(tool)
        assert converted.output_schema is not None


# --- The async rule, which nothing else enforces --------------------------
#
# A tool that does I/O must be `async def`; the runtime hands a sync tool to a
# thread pool, at a thread per call. Ported code arrives sync, because the
# library it came from was, and neither ruff nor `build_server` looks at this.
#
# So: read the source of every *sync* tool and refuse the calls that can only
# be blocking. This is a floor, not a proof — it names what it is sure of and
# stays quiet about the rest, because a gate that cries wolf gets deleted.

#: Every call into these is blocking; none has an awaitable form.
BLOCKING_MODULES = frozenset(
    {
        "ftplib",
        "http",
        "imaplib",
        "requests",
        "smtplib",
        "socket",
        "subprocess",
        "telnetlib",
        "urllib",
    }
)

#: Blocking members of modules whose other members are fine.
BLOCKING_CALLS = frozenset(
    {
        "httpx.Client",
        "httpx.delete",
        "httpx.get",
        "httpx.head",
        "httpx.options",
        "httpx.patch",
        "httpx.post",
        "httpx.put",
        "httpx.request",
        "httpx.stream",
        "time.sleep",
    }
)


def _dotted(node: ast.expr) -> str | None:
    """``a.b.c`` for an attribute chain rooted in a plain name, else ``None``."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _imported_as(tree: ast.Module) -> dict[str, str]:
    """Each name a module binds, mapped to the dotted path it really names."""
    bound = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return bound


def _blocking(call: ast.Call, bound: dict[str, str]) -> str | None:
    """The call's real dotted name, if calling it would block the event loop."""
    dotted = _dotted(call.func)
    if dotted is None:
        return None
    head, _, rest = dotted.partition(".")
    resolved = (
        f"{bound[head]}.{rest}" if head in bound and rest else bound.get(head, dotted)
    )
    if resolved.split(".")[0] in BLOCKING_MODULES or resolved in BLOCKING_CALLS:
        return resolved
    return None


def _reached(
    name: str, functions: dict[str, ast.FunctionDef], seen: set[str]
) -> list[ast.Call]:
    """Every call ``name`` makes, following the module's own helpers into it."""
    if name in seen or name not in functions:
        return []
    seen.add(name)
    calls = []
    for node in ast.walk(functions[name]):
        if isinstance(node, ast.Call):
            calls.append(node)
            if (called := _dotted(node.func)) is not None:
                calls.extend(_reached(called, functions, seen))
    return calls


def blocking_calls(function: Callable[..., Any]) -> list[str]:
    """Blocking calls ``function`` makes, directly or through its own module."""
    source_file = inspect.getsourcefile(function)
    if source_file is None:  # not written down anywhere we can read
        return []
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    bound = _imported_as(tree)
    found = [
        resolved
        for call in _reached(function.__name__, functions, set())
        if (resolved := _blocking(call, bound)) is not None
    ]
    return sorted(set(found))


@pytest.mark.parametrize("toolset", TOOLSET_NAMES)
def test_sync_tools_do_no_blocking_io(toolset):
    """A tool that blocks must be `async def`, so it does not hold a thread."""
    module = importlib.import_module(toolset.replace("-", "_") + ".tools")
    for tool in module.TOOLS:
        function = getattr(tool, "func", None)
        if function is None:  # already a coroutine, which is the point
            continue
        blocking = blocking_calls(function)
        assert not blocking, (
            f"{toolset}: sync tool {tool.name!r} calls {', '.join(blocking)}. "
            f"Make it `async def` and await an awaitable equivalent, or move "
            f"the blocking work behind a tool that is."
        )


# A module the gate reads but never runs, so it can name libraries this repo
# does not install. The blocking ones are the shapes a port actually arrives
# in; the innocent ones are next to them in the same module, because a gate
# that flags those is a gate someone turns off.
SAMPLE = """\
import time

import httpx
from urllib.request import urlopen


def direct():
    import requests

    return requests.get("https://example.com")


def aliased():
    from requests import post

    return post("https://example.com")


def stdlib_url():
    return urlopen("https://example.com")


def _fetch():
    return httpx.get("https://example.com")


def through_a_helper():
    return _fetch()


def sync_client():
    with httpx.Client() as client:
        return client.get("https://example.com")


def waits():
    time.sleep(1)


def measures_time():
    return {"at": time.time()}


def builds_an_async_client():
    return httpx.AsyncClient()
"""


@pytest.fixture
def sample(tmp_path, monkeypatch):
    """The sample module above, imported so its functions carry a source file."""
    (tmp_path / "sample_tools.py").write_text(SAMPLE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return importlib.import_module("sample_tools")


@pytest.mark.parametrize(
    ("function", "expected"),
    [
        ("direct", ["requests.get"]),
        ("aliased", ["requests.post"]),
        ("stdlib_url", ["urllib.request.urlopen"]),
        ("through_a_helper", ["httpx.get"]),
        ("sync_client", ["httpx.Client"]),
        ("waits", ["time.sleep"]),
    ],
)
def test_blocking_calls_are_named(sample, function, expected):
    assert blocking_calls(getattr(sample, function)) == expected


@pytest.mark.parametrize("function", ["measures_time", "builds_an_async_client"])
def test_calls_that_do_not_block_are_left_alone(sample, function):
    """`time.time` and an `AsyncClient` sit beside the calls that do block."""
    assert blocking_calls(getattr(sample, function)) == []
