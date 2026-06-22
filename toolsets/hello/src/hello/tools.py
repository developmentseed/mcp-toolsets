"""LangChain tools for the hello toolset — the smallest thing that deploys.

Use this as the starting point for a real toolset (or run
``./scripts/new-toolset <name>``): replace ``hello`` with your own ``@tool``
functions and keep the ``TOOLS`` export.
"""

from langchain_core.tools import tool


@tool
def hello(name: str = "world") -> str:
    """Return a friendly greeting (docstrings and type hints ARE the MCP schema)."""
    return f"Hello, {name}!"


TOOLS = [hello]
