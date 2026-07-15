"""The base contract every tool return follows.

A tool returns one dict per call, in one of two shapes:

- :class:`ToolResult` — success: a ``message`` (the text the model reads)
  plus any data keys the tool declares, captured into session state.
- :class:`ToolError` — failure: a machine-readable ``error`` kind and a
  ``detail`` saying what happened or what to do next.

Subclass :class:`ToolResult` per tool, one ``NotRequired`` field per data
key, and annotate the ``@tool`` function with the union::

    class SearchDatasetsResult(ToolResult):
        datasets: NotRequired[list[dict[str, Any]]]

    @tool
    async def search_datasets(query: str) -> SearchDatasetsResult | ToolError:
        ...

``mcp_runtime.fastmcp_output`` derives the tool's MCP ``outputSchema`` from
the annotation and refuses to serve a tool that breaks the contract — a
deploy-time gate, not a convention.
"""

from typing import Any, TypedDict

from typing_extensions import TypeIs


class ToolResult(TypedDict):
    """A successful tool return: a ``message`` plus declared data keys."""

    message: str


class ToolError(TypedDict):
    """A structured tool error: what kind, and what to do about it."""

    error: str
    detail: str


def is_error(result: dict[str, Any] | ToolError) -> TypeIs[ToolError]:
    """Whether a helper's raw dict is an error return (truthy ``error`` key)."""
    return bool(result.get("error"))
