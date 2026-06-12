"""Chat with every toolset behind an mcp-toolsets index URL.

Point ``mcp-agent`` at an index root (anything serving a ``connections`` map
shaped for ``MultiServerMCPClient``) or directly at a single MCP endpoint;
it loads every server's tools and lets a Mistral model drive them in an
interactive chat. Requires ``MISTRAL_API_KEY``.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Annotated, Any, cast

import httpx
import typer
from langchain.agents import create_agent
from mcp.client.streamable_http import create_mcp_http_client
from mcp.shared.exceptions import McpError
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mistralai import ChatMistralAI
from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.console import Console
from rich.markdown import Markdown

DEFAULT_MODEL = "mistral-small-latest"
SYSTEM_PROMPT = (
    "You are a helpful assistant with tools from one or more MCP toolsets. "
    "Use them whenever they can ground your answer; otherwise answer directly."
)

app = typer.Typer(no_args_is_help=True, help=__doc__)
console = Console()


class AgentSettings(BaseSettings):
    """Agent configuration, validated from the environment or a .env file.

    The CLI takes the URL and model as arguments; the web UI (``web.py``)
    reads ``MCP_URL`` and ``MISTRAL_MODEL`` from here instead.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mistral_api_key: SecretStr
    mistral_model: str = DEFAULT_MODEL
    mcp_url: str = "http://localhost:8000/mcp"
    chainlit_port: int = Field(default=8080, ge=1, le=65535)


def connections_from(url: str, payload: Any) -> dict[str, Any]:
    """Extract an index payload's connections map, else treat url as one server."""
    if isinstance(payload, dict) and isinstance(payload.get("connections"), dict):
        return payload["connections"]
    return {"server": {"transport": "streamable_http", "url": url}}


def credential_headers_from(payload: Any) -> dict[str, list[str]] | None:
    """Per-toolset credential header names from an index payload.

    ``None`` means the payload was not an index (a direct single-server URL),
    so no declarations are available.
    """
    if not (isinstance(payload, dict) and isinstance(payload.get("toolsets"), list)):
        return None
    return {
        entry["name"]: [
            header.lower() for header in entry.get("credential_headers", [])
        ]
        for entry in payload["toolsets"]
        if isinstance(entry, dict) and entry.get("name")
    }


# Connection failures an agent should report rather than crash on.
CONNECT_ERRORS = (httpx.HTTPError, OSError, McpError)


def first_leaf(error: BaseException) -> BaseException:
    """Unwrap (possibly nested) ExceptionGroups to the first real exception."""
    while isinstance(error, BaseExceptionGroup):
        error = error.exceptions[0]
    return error


def connect_error_hint(url: str) -> str:
    """A nudge for the most common misconfiguration: a missing /mcp path."""
    if url.rstrip("/").endswith("/mcp"):
        return ""
    return (
        " Hint: single-toolset servers serve MCP under /mcp "
        "(e.g. http://localhost:8000/mcp); only an index is served at the root."
    )


def health_url_for(url: str) -> str | None:
    """Derive a direct MCP endpoint's sibling /health URL, if there is one."""
    base = url.rstrip("/")
    return base.removesuffix("/mcp") + "/health" if base.endswith("/mcp") else None


async def single_server_credential_headers(
    client: httpx.AsyncClient, url: str
) -> dict[str, list[str]] | None:
    """Ask a direct MCP endpoint's /health which credential headers it reads.

    Returns ``None`` when there is no health route or it doesn't advertise
    credentials (e.g. a non-mcp-toolsets server).
    """
    health_url = health_url_for(url)
    if health_url is None:
        return None
    try:
        health = (await client.get(health_url)).json()
        headers = health.get("credential_headers")
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    if not isinstance(headers, list):
        return None
    return {"server": [str(header).lower() for header in headers]}


async def fetch_connections(
    url: str,
) -> tuple[dict[str, Any], dict[str, list[str]] | None]:
    """Resolve a URL to a MultiServerMCPClient config plus credential needs."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
        try:
            payload = (await client.get(url)).json()
        except (httpx.HTTPError, ValueError):
            payload = None
        connections = connections_from(url, payload)
        required = credential_headers_from(payload)
        if required is None:
            required = await single_server_credential_headers(client, url)
    return connections, required


_credentials: ContextVar[dict[str, str] | None] = ContextVar(
    "user_credentials", default=None
)


@contextmanager
def user_credentials(headers: dict[str, str] | None) -> Iterator[None]:
    """Provide the calling user's credential headers for the duration.

    This is how an agent passes a user's secrets to the tools without the
    model ever seeing them: they ride the MCP transport, not the conversation.
    The agent is built once; wrap each turn (``run_turn``) in this and the
    tool calls made inside read the values at request time, so one long-lived
    agent serves many users with different credentials.
    """
    token = _credentials.set(headers)
    try:
        yield
    finally:
        _credentials.reset(token)


def credential_client_factory(allowed: list[str] | None) -> Any:
    """Build an httpx client factory injecting the current user's credentials.

    Only headers named in ``allowed`` (the toolset's advertised declaration)
    are injected, so unrelated toolsets never receive them; ``None`` means no
    declaration was discoverable (a server the user pointed at directly) and
    every provided header is sent.
    """
    wanted = None if allowed is None else {header.lower() for header in allowed}

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        provided = _credentials.get() or {}
        send = {
            header: value
            for header, value in provided.items()
            if wanted is None or header.lower() in wanted
        }
        return create_mcp_http_client(
            headers={**(headers or {}), **send}, timeout=timeout, auth=auth
        )

    return factory


def with_credential_support(
    connections: dict[str, Any], required: dict[str, list[str]] | None
) -> dict[str, Any]:
    """Wire each connection to inject per-user credentials at call time."""
    return {
        name: {
            **connection,
            "httpx_client_factory": credential_client_factory(
                None if required is None else required.get(name, [])
            ),
        }
        for name, connection in connections.items()
    }


async def build_agent(
    url: str, model: str, api_key: SecretStr
) -> tuple[Any, dict[str, Any], list[BaseTool]]:
    """Discover the servers behind ``url`` and build a tool-calling agent.

    Built once per process/session: per-user credentials are not baked in but
    read from :func:`user_credentials` on every tool call.
    """
    connections, required = await fetch_connections(url)
    tools = await MultiServerMCPClient(
        with_credential_support(connections, required)
    ).get_tools()
    agent = create_agent(
        ChatMistralAI(model_name=model, api_key=api_key),
        tools,
        system_prompt=SYSTEM_PROMPT,
    )
    return agent, connections, tools


async def run_turn(
    agent: Any, messages: list[BaseMessage], text: str
) -> tuple[list[BaseMessage], list[BaseMessage]]:
    """Run one chat turn; return the full history and this turn's new messages."""
    state = {"messages": [*messages, HumanMessage(text)]}
    result = await agent.ainvoke(cast(Any, state))
    history: list[BaseMessage] = result["messages"]
    return history, history[len(messages) + 1 :]


async def chat_loop(url: str, model: str, api_key: SecretStr) -> None:
    try:
        agent, connections, tools = await build_agent(url, model, api_key)
    except* CONNECT_ERRORS as group:
        console.print(
            f"[red]Could not reach the MCP server(s) behind {url}: "
            f"{first_leaf(group)}[/red]"
        )
        if hint := connect_error_hint(url):
            console.print(f"[yellow]{hint.strip()}[/yellow]")
        raise typer.Exit(1) from None

    console.print(
        f"Connected to [bold]{len(connections)}[/bold] server(s): "
        f"{', '.join(connections)}"
    )
    console.print(f"[dim]{len(tools)} tools: {', '.join(t.name for t in tools)}[/dim]")
    console.print("[dim]Type a message, or quit to exit.[/dim]")

    messages: list[BaseMessage] = []
    while True:
        try:
            line = console.input("[bold cyan]you>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("quit", "exit"):
            break
        try:
            messages, new_messages = await run_turn(agent, messages, line)
        except Exception as error:  # noqa: BLE001 - keep the chat alive
            console.print(f"[red]{error}[/red]")
            continue
        for message in new_messages:
            for call in getattr(message, "tool_calls", None) or []:
                console.print(f"[dim]→ {call['name']} {call['args']}[/dim]")
        console.print(Markdown(str(messages[-1].content)))


@app.command()
def chat(
    url: Annotated[
        str,
        typer.Argument(
            help="Index URL serving a connections map, or a single MCP endpoint."
        ),
    ],
    model: Annotated[str, typer.Option("--model", help="Mistral model.")] = (
        DEFAULT_MODEL
    ),
) -> None:
    """Discover the MCP servers behind URL and chat with their tools."""
    try:
        settings = AgentSettings()
    except ValidationError:
        console.print("[red]MISTRAL_API_KEY is not set (environment or .env)[/red]")
        raise typer.Exit(1) from None
    asyncio.run(chat_loop(url, model, settings.mistral_api_key))
