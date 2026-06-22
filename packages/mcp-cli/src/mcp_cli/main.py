"""Interact with an MCP tool service over streamable HTTP.

Commands: ``list`` (tool table), ``call <tool> key=value ...`` (one-shot
invocation), ``repl`` (interactive session). Argument values are parsed as
JSON, falling back to plain strings.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

import typer
from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client
from rich.console import Console
from rich.table import Table

DEFAULT_URL = "http://localhost:8000/mcp"

app = typer.Typer(no_args_is_help=True, help=__doc__)
console = Console()

UrlOption = Annotated[str, typer.Option("--url", help="MCP server URL.")]
HeaderOption = Annotated[
    list[str] | None,
    typer.Option(
        "--header",
        "-H",
        help='HTTP header sent with every request, as "Name: value" (repeatable) — '
        "e.g. per-user credentials a tool reads server-side.",
    ),
]


def parse_headers(pairs: list[str] | None) -> dict[str, str] | None:
    """Parse ``Name: value`` header pairs (as curl's ``-H``)."""
    if not pairs:
        return None
    headers = {}
    for pair in pairs:
        name, sep, value = pair.partition(":")
        if not sep or not name.strip() or not value.strip():
            raise ValueError(f'expected "Name: value", got {pair!r}')
        headers[name.strip()] = value.strip()
    return headers


def parse_tool_args(pairs: list[str]) -> dict[str, Any]:
    """Parse ``key=value`` pairs; values are JSON with string fallback."""
    arguments: dict[str, Any] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"expected key=value, got {pair!r}")
        try:
            arguments[key] = json.loads(value)
        except json.JSONDecodeError:
            arguments[key] = value
    return arguments


async def _with_session[T](
    url: str,
    action: Callable[[ClientSession], Awaitable[T]],
    headers: dict[str, str] | None = None,
) -> T:
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await action(session)


def _tools_table(tools: list[types.Tool]) -> Table:
    table = Table("Tool", "Description", "Arguments")
    for tool in tools:
        properties = tool.inputSchema.get("properties", {})
        required = set(tool.inputSchema.get("required", []))
        arguments = ", ".join(
            f"{name}: {spec.get('type', 'any')}"
            + ("" if name in required else " (optional)")
            for name, spec in properties.items()
        )
        table.add_row(tool.name, tool.description or "", arguments)
    return table


def _print_result(result: types.CallToolResult) -> None:
    if result.isError:
        console.print("[bold red]Tool error[/bold red]")
    for block in result.content:
        if isinstance(block, types.TextContent):
            console.print(block.text)
    if result.structuredContent is not None:
        console.print_json(json.dumps(result.structuredContent))


def _parse_headers_or_exit(header: list[str] | None) -> dict[str, str] | None:
    try:
        return parse_headers(header)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


@app.command("list")
def list_tools(url: UrlOption = DEFAULT_URL, header: HeaderOption = None) -> None:
    """List the server's tools with their argument schemas."""
    headers = _parse_headers_or_exit(header)

    async def action(session: ClientSession) -> list[types.Tool]:
        return (await session.list_tools()).tools

    console.print(_tools_table(asyncio.run(_with_session(url, action, headers))))


@app.command()
def call(
    tool: Annotated[str, typer.Argument(help="Tool name.")],
    args: Annotated[
        list[str] | None, typer.Argument(help="Arguments as key=value pairs.")
    ] = None,
    url: UrlOption = DEFAULT_URL,
    header: HeaderOption = None,
) -> None:
    """Call a tool once and print its result."""
    headers = _parse_headers_or_exit(header)
    try:
        arguments = parse_tool_args(args or [])
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error

    async def action(session: ClientSession) -> types.CallToolResult:
        return await session.call_tool(tool, arguments)

    _print_result(asyncio.run(_with_session(url, action, headers)))


@app.command()
def repl(url: UrlOption = DEFAULT_URL, header: HeaderOption = None) -> None:
    """Interactive loop on a single session: `list`, `<tool> key=value ...`, `quit`."""
    headers = _parse_headers_or_exit(header)

    async def action(session: ClientSession) -> None:
        tools = (await session.list_tools()).tools
        console.print(f"Connected to [bold]{url}[/bold]")
        console.print("Commands: list | <tool> key=value ... | quit")
        while True:
            try:
                line = console.input("[bold cyan]mcp>[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line in ("quit", "exit"):
                break
            if line == "list":
                console.print(_tools_table(tools))
                continue
            name, *pairs = line.split()
            try:
                arguments = parse_tool_args(pairs)
            except ValueError as error:
                console.print(f"[red]{error}[/red]")
                continue
            try:
                _print_result(await session.call_tool(name, arguments))
            except Exception as error:  # noqa: BLE001 - keep the repl alive
                console.print(f"[red]{error}[/red]")

    asyncio.run(_with_session(url, action, headers))
