"""Chainlit chat UI over the same agent as the ``mcp-agent`` CLI.

Run locally with ``uv run mcp-agent-web``. Configuration comes from
``AgentSettings`` (environment or .env): ``PROVIDER_MODEL`` and
``PROVIDER_API_KEY`` (both required — pick a provider:model and install its
package), ``MCP_URL`` (index root or single MCP endpoint, default
``http://localhost:8000/mcp``) and ``CHAINLIT_PORT`` (default 8080).

Per-user credentials: every credential header the connected toolsets
advertise gets a field in the chat's settings panel; values are sent as HTTP
headers on the MCP calls — only to the toolsets that declared them — so the
model and the chat history never see them. The agent is built once per
session; credentials apply per message via ``user_credentials``, the same
mechanism a public multi-user API would use with one shared agent.
"""

import os
import sys
from pathlib import Path
from typing import Any

import chainlit as cl
from chainlit.input_widget import InputWidget, TextInput
from langchain_core.messages import BaseMessage, ToolMessage
from pydantic import ValidationError

from mcp_agent.main import (
    PROVIDER_HELP,
    AgentSettings,
    build_agent,
    connect_error_hint,
    fetch_connections,
    first_leaf,
    run_turn,
    user_credentials,
)


@cl.on_chat_start
async def start() -> None:
    settings = AgentSettings()
    _, required = await fetch_connections(settings.mcp_url)
    header_names = sorted(
        {name for names in (required or {}).values() for name in names}
    )
    if header_names:
        fields: list[InputWidget] = [
            TextInput(id=name, label=name) for name in header_names
        ]
        await cl.ChatSettings(fields).send()
    try:
        agent, connections, tools = await build_agent(
            settings.mcp_url, settings.provider_model, settings.provider_api_key
        )
    except Exception as error:  # noqa: BLE001 - surface in the UI, not the logs
        await cl.Message(
            f"Could not reach the MCP server(s) behind {settings.mcp_url}: "
            f"{first_leaf(error)}.{connect_error_hint(settings.mcp_url)}"
        ).send()
        return
    cl.user_session.set("agent", agent)
    cl.user_session.set("messages", [])
    await cl.Message(
        f"Connected to **{len(connections)}** server(s) "
        f"({', '.join(connections)}) with **{len(tools)}** tools: "
        f"{', '.join(tool.name for tool in tools)}."
    ).send()
    if header_names:
        needing = ", ".join(
            f"{toolset} ({', '.join(names)})"
            for toolset, names in sorted((required or {}).items())
            if names
        )
        await cl.Message(
            f"Some tools act on your behalf and need credentials: {needing}. "
            "Set them in the settings panel (⚙ by the message box); each is "
            "sent only to the toolset that declares it, never to the model."
        ).send()


@cl.on_settings_update
async def apply_credentials(values: dict[str, Any]) -> None:
    headers = {
        name: value.strip()
        for name, value in values.items()
        if isinstance(value, str) and value.strip()
    }
    cl.user_session.set("credentials", headers or None)
    await cl.Message("Credentials updated — your next tool calls will use them.").send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    agent = cl.user_session.get("agent")
    if agent is None:
        await cl.Message(
            "Not connected to any MCP server — fix MCP_URL and reload the page."
        ).send()
        return
    messages: list[BaseMessage] = cl.user_session.get("messages") or []
    credentials: dict[str, str] | None = cl.user_session.get("credentials")
    try:
        with user_credentials(credentials):
            history, new_messages = await run_turn(agent, messages, message.content)
    except Exception as error:  # noqa: BLE001 - surface in the UI, keep chatting
        await cl.Message(f"Error: {error}").send()
        return
    cl.user_session.set("messages", history)

    tool_outputs: dict[str, Any] = {
        msg.tool_call_id: msg.content
        for msg in new_messages
        if isinstance(msg, ToolMessage)
    }
    for msg in new_messages:
        for call in getattr(msg, "tool_calls", None) or []:
            async with cl.Step(name=call["name"]) as step:
                step.input = call["args"]
                step.output = str(tool_outputs.get(call["id"], ""))
    await cl.Message(str(history[-1].content)).send()


def main() -> None:
    """Console entry point (``mcp-agent-web``)."""
    from chainlit.cli import run_chainlit

    try:
        settings = AgentSettings()
    except ValidationError:
        print(PROVIDER_HELP, file=sys.stderr)
        raise SystemExit(1) from None
    os.environ["CHAINLIT_PORT"] = str(settings.chainlit_port)
    run_chainlit(str(Path(__file__).resolve()))
