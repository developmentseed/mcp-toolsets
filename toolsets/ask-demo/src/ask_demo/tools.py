"""LangChain tools demonstrating tools that ask the user a question.

Each tool cannot finish without the user, so it calls ``ask`` with a question
and the schema of the answer. The first time through, the call ends there and
the agent puts the question to the user; the agent then calls the tool again,
from the start, and ``ask`` returns what the user gave. Between them the
questions use every kind of field an MCP form request allows: numbers with
bounds, strings with a format or a pattern, booleans, a choice from a list,
several choices, a default, and a description. The work each one does is
stubbed.
"""

from langchain_core.tools import tool

from mcp_runtime.questions import ask
from mcp_runtime.tool_result import ToolResult

WHICH_YEAR = {
    "type": "object",
    "properties": {
        "year": {
            "type": "integer",
            "minimum": 1940,
            "maximum": 2026,
            "description": "The year to download",
        },
        "notify": {
            "type": "string",
            "format": "email",
            "description": "An address to email when it is ready",
        },
    },
    "required": ["year"],
}


@tool
async def download(dataset: str) -> ToolResult:
    """Download one year of a dataset, asking the user which year."""
    # Ask first: the tool runs from the start on both calls, so work done
    # before asking is done twice.
    chosen = ask(f"Which year of {dataset}?", WHICH_YEAR)
    if chosen is None:  # the user declined
        return ToolResult(
            message=f"No year chosen, so nothing downloaded from {dataset}."
        )
    done = f"Downloaded {dataset} for {chosen['year']}."
    if notify := chosen.get("notify"):
        done += f" Told {notify}."
    return ToolResult(message=done)


HOW_OFTEN = {
    "type": "object",
    "properties": {
        "frequency": {
            "type": "string",
            "oneOf": [
                {"const": "daily", "title": "Every day"},
                {"const": "weekly", "title": "Every Monday"},
                {"const": "monthly", "title": "The first of the month"},
            ],
            "default": "weekly",
        },
        "start": {
            "type": "string",
            "format": "date",
            "description": "The first day to send",
        },
        "digest": {
            "type": "boolean",
            "default": True,
            "description": "One summary rather than a message per change",
        },
    },
    "required": ["frequency", "start"],
}


@tool
async def subscribe(dataset: str) -> ToolResult:
    """Subscribe the user to changes in a dataset, asking how often."""
    chosen = ask(f"How often, for {dataset}?", HOW_OFTEN)
    if chosen is None:
        return ToolResult(message=f"Not subscribed to {dataset}.")
    kind = "a digest" if chosen.get("digest", True) else "every change"
    return ToolResult(
        message=f"Subscribed to {dataset}: {chosen['frequency']} from "
        f"{chosen['start']}, as {kind}."
    )


WHAT_TO_EXPORT = {
    "type": "object",
    "properties": {
        "variables": {
            "type": "array",
            "items": {"enum": ["t2m", "tp", "sp", "u10", "v10"]},
            "description": "Which variables to include",
        },
        "format": {
            "type": "string",
            "enum": ["netcdf", "grib", "zarr"],
            "default": "netcdf",
        },
    },
    "required": ["variables", "format"],
}


@tool
async def export(dataset: str) -> ToolResult:
    """Export variables of a dataset, asking which and in what format."""
    chosen = ask(f"What to export from {dataset}?", WHAT_TO_EXPORT)
    if chosen is None:
        return ToolResult(message=f"Nothing exported from {dataset}.")
    return ToolResult(
        message=f"Exporting {', '.join(chosen['variables'])} of {dataset} "
        f"as {chosen['format']}."
    )


WHERE_TO_SEND = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "format": "uri",
            "description": "Where to POST each event",
        },
        "label": {
            "type": "string",
            "pattern": "^[a-z][a-z0-9-]*$",
            "minLength": 3,
            "maxLength": 20,
            "description": "A short name: lowercase letters, digits and dashes",
        },
    },
    "required": ["url", "label"],
}


@tool
async def register_webhook() -> ToolResult:
    """Register a webhook for dataset events, asking where to send them."""
    chosen = ask("Where should events go?", WHERE_TO_SEND)
    if chosen is None:
        return ToolResult(message="No webhook registered.")
    return ToolResult(
        message=f"Webhook {chosen['label']} will POST to {chosen['url']}."
    )


TOOLS = [download, subscribe, export, register_webhook]
