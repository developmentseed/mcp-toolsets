"""Chat with every toolset behind an mcp-toolsets index URL.

Point ``mcp-agent`` at an index root (anything serving a ``connections`` map
shaped for ``MultiServerMCPClient``) or directly at a single MCP endpoint;
it loads every server's tools and lets a Mistral model drive them in an
interactive chat. Requires ``MISTRAL_API_KEY``.
"""

import asyncio
from typing import Annotated, Any, cast

import httpx
import typer
from langchain.agents import create_agent
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


def fetch_connections(url: str) -> dict[str, Any]:
    """Resolve an index or single-server URL to a MultiServerMCPClient config."""
    try:
        payload = httpx.get(url, follow_redirects=True, timeout=10.0).json()
    except (httpx.HTTPError, ValueError):
        payload = None
    return connections_from(url, payload)


async def build_agent(
    url: str, model: str, api_key: SecretStr
) -> tuple[Any, dict[str, Any], list[BaseTool]]:
    """Discover the servers behind ``url`` and build a tool-calling agent."""
    connections = fetch_connections(url)
    tools = await MultiServerMCPClient(connections).get_tools()
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
    except* (httpx.HTTPError, OSError) as group:
        console.print(
            f"[red]Could not reach the MCP server(s) behind {url}: "
            f"{group.exceptions[0]}[/red]"
        )
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
