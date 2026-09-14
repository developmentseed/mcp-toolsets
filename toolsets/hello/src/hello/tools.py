"""LangChain tools for the hello toolset — the smallest thing that deploys.

Use this as the starting point for a real toolset (or run
``uv run mcp-toolset new <name>``): replace ``hello`` with your own ``@tool``
functions and keep the ``TOOLS`` export.
"""

from langchain_core.tools import tool

from mcp_runtime.tool_result import ToolResult


@tool
def hello(name: str = "world") -> ToolResult:
    """Return a friendly greeting (docstrings and type hints ARE the MCP schema)."""
    return ToolResult(message=f"Hello, {name}!")


TOOLS = [hello]
