"""Chainlit chat UI over the same agent as the ``mcp-agent`` CLI.

Run locally with ``uv run mcp-agent-web``. Configuration comes from
``AgentSettings`` (environment or .env): ``MISTRAL_API_KEY`` (required),
``MCP_URL`` (index root or single MCP endpoint, default
``http://localhost:8000/mcp``), ``MISTRAL_MODEL`` and ``CHAINLIT_PORT``
(default 8080).
"""

import os
import sys
from pathlib import Path
from typing import Any

import chainlit as cl
from langchain_core.messages import BaseMessage, ToolMessage
from pydantic import ValidationError

from mcp_agent.main import AgentSettings, build_agent, run_turn


@cl.on_chat_start
async def start() -> None:
    settings = AgentSettings()
    agent, connections, tools = await build_agent(
        settings.mcp_url, settings.mistral_model, settings.mistral_api_key
    )
    cl.user_session.set("agent", agent)
    cl.user_session.set("messages", [])
    await cl.Message(
        f"Connected to **{len(connections)}** server(s) "
        f"({', '.join(connections)}) with **{len(tools)}** tools: "
        f"{', '.join(tool.name for tool in tools)}."
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    agent = cl.user_session.get("agent")
    messages: list[BaseMessage] = cl.user_session.get("messages") or []
    try:
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
        print("MISTRAL_API_KEY is not set (environment or .env)", file=sys.stderr)
        raise SystemExit(1) from None
    os.environ["CHAINLIT_PORT"] = str(settings.chainlit_port)
    run_chainlit(str(Path(__file__).resolve()))
