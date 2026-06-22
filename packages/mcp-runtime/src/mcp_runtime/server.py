"""Discover a toolset's LangChain tools and serve them over MCP.

The runtime is driven by environment variables so the same image works for
every toolset:

- ``TOOLSET`` (required): the toolset directory name, e.g. ``dataset-search``.
- ``TOOLSET_MODULE`` (optional): module exporting ``TOOLS``; defaults to the
  convention ``<toolset>.tools`` (``dataset-search`` -> ``dataset_search.tools``).
- ``HOST`` (default ``127.0.0.1``; the Helm chart sets ``0.0.0.0``).
- ``PORT`` (default ``8000``).
"""

import importlib
from ipaddress import IPv4Address

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import to_fastmcp
from mcp.server.fastmcp import FastMCP
from pydantic import Field, IPvAnyAddress
from pydantic_settings import BaseSettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class RuntimeSettings(BaseSettings):
    """Runtime configuration, validated from the environment."""

    toolset: str
    toolset_module: str | None = None
    host: IPvAnyAddress = IPv4Address("127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)


def toolset_module_name(toolset: str) -> str:
    """Derive the tools module from a toolset directory name by convention."""
    return toolset.replace("-", "_") + ".tools"


def load_tools(module_name: str) -> list[BaseTool]:
    """Import a tools module and return its ``TOOLS`` export."""
    module = importlib.import_module(module_name)
    tools = getattr(module, "TOOLS", None)
    if not tools:
        raise RuntimeError(f"module {module_name!r} must export a non-empty TOOLS list")
    for tool in tools:
        if not isinstance(tool, BaseTool):
            raise RuntimeError(
                f"{module_name}.TOOLS entries must be LangChain BaseTool "
                f"instances, got {type(tool).__name__}"
            )
    return list(tools)


def load_credential_headers(module_name: str) -> list[str]:
    """Return a tools module's optional ``CREDENTIAL_HEADERS`` export.

    Names of per-user HTTP headers the toolset's tools read (via
    ``mcp_runtime.credentials``). Advertised in ``/health`` and the index so
    clients attach each credential only to the toolsets that declare it.
    """
    module = importlib.import_module(module_name)
    headers = getattr(module, "CREDENTIAL_HEADERS", [])
    if not isinstance(headers, list) or not all(
        isinstance(header, str) and header for header in headers
    ):
        raise RuntimeError(
            f"{module_name}.CREDENTIAL_HEADERS must be a list of header names"
        )
    return sorted(header.lower() for header in headers)


def build_server(
    toolset: str,
    module_name: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    """Build a stateless FastMCP server exposing the toolset's TOOLS."""
    module_name = module_name or toolset_module_name(toolset)
    tools = load_tools(module_name)
    credential_headers = load_credential_headers(module_name)
    server = FastMCP(
        name=f"mcp-{toolset}",
        tools=[to_fastmcp(tool) for tool in tools],
        host=host,
        port=port,
        stateless_http=True,
    )

    tool_names = [tool.name for tool in tools]

    @server.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> Response:
        return JSONResponse(
            {
                "status": "ok",
                "tools": tool_names,
                "credential_headers": credential_headers,
            }
        )

    return server


def main() -> None:
    """Console entry point (``mcp-serve``)."""
    settings = RuntimeSettings()
    server = build_server(
        toolset=settings.toolset,
        module_name=settings.toolset_module,
        host=str(settings.host),
        port=settings.port,
    )
    server.run(transport="streamable-http")
