"""LangChain tools demonstrating tools that ask the user a question.

Each tool cannot finish without the user, so it calls ``ask`` with a question
and a pydantic model of the answer. The first time through, the call ends
there and the agent puts the question to the user; the agent then calls the
tool again, from the start, and ``ask`` returns the answer as an instance of
the model. Between them the models use every kind of field an MCP form request
allows: numbers with bounds, strings with a format or a pattern, booleans, a
choice from a list, several choices, a default, and a description. The work
each one does is stubbed.
"""

from datetime import date
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, EmailStr, Field, HttpUrl

from mcp_runtime.questions import ask
from mcp_runtime.tool_result import ToolResult


class WhichYear(BaseModel):
    year: int = Field(ge=1940, le=2026, description="The year to download")
    notify: EmailStr | None = Field(
        None, description="An address to email when it is ready"
    )


@tool
async def download(dataset: str) -> ToolResult:
    """Download one year of a dataset, asking the user which year."""
    # Ask first: the tool runs from the start on both calls, so work done
    # before asking is done twice.
    chosen = ask(f"Which year of {dataset}?", WhichYear)
    if chosen is None:  # the user declined
        return ToolResult(
            message=f"No year chosen, so nothing downloaded from {dataset}."
        )
    done = f"Downloaded {dataset} for {chosen.year}."
    if chosen.notify:
        done += f" Told {chosen.notify}."
    return ToolResult(message=done)


class HowOften(BaseModel):
    frequency: Literal["daily", "weekly", "monthly"] = "weekly"
    start: date = Field(description="The first day to send")
    digest: bool = Field(
        True, description="One summary rather than a message per change"
    )


@tool
async def subscribe(dataset: str) -> ToolResult:
    """Subscribe the user to changes in a dataset, asking how often."""
    chosen = ask(f"How often, for {dataset}?", HowOften)
    if chosen is None:
        return ToolResult(message=f"Not subscribed to {dataset}.")
    kind = "a digest" if chosen.digest else "every change"
    return ToolResult(
        message=f"Subscribed to {dataset}: {chosen.frequency} from "
        f"{chosen.start}, as {kind}."
    )


class WhatToExport(BaseModel):
    variables: list[Literal["t2m", "tp", "sp", "u10", "v10"]] = Field(
        description="Which variables to include"
    )
    format: Literal["netcdf", "grib", "zarr"] = "netcdf"


@tool
async def export(dataset: str) -> ToolResult:
    """Export variables of a dataset, asking which and in what format."""
    chosen = ask(f"What to export from {dataset}?", WhatToExport)
    if chosen is None:
        return ToolResult(message=f"Nothing exported from {dataset}.")
    return ToolResult(
        message=f"Exporting {', '.join(chosen.variables)} of {dataset} "
        f"as {chosen.format}."
    )


class WhereToSend(BaseModel):
    url: HttpUrl = Field(description="Where to POST each event")
    label: str = Field(
        pattern="^[a-z][a-z0-9-]*$",
        min_length=3,
        max_length=20,
        description="A short name: lowercase letters, digits and dashes",
    )


@tool
async def register_webhook() -> ToolResult:
    """Register a webhook for dataset events, asking where to send them."""
    chosen = ask("Where should events go?", WhereToSend)
    if chosen is None:
        return ToolResult(message="No webhook registered.")
    return ToolResult(message=f"Webhook {chosen.label} will POST to {chosen.url}.")


TOOLS = [download, subscribe, export, register_webhook]
