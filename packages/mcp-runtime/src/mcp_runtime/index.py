"""Serve a public directory of every deployed toolset.

``mcp-index`` runs as one in-cluster service alongside the toolsets: it lists
the toolset Services via the Kubernetes API (they all carry the
``mcp-toolsets/toolset`` label), asks each one's ``/health`` route for its
tool names, and serves the aggregate as JSON at ``/`` (interactive docs at
``/docs``). Driven by environment variables:

- ``PUBLIC_URL`` (required): external base URL the toolsets are served under,
  e.g. ``https://mcp.example.com``.
- ``HOST`` (default ``127.0.0.1``; the Helm chart sets ``0.0.0.0``).
- ``PORT`` (default ``8000``).
"""

import asyncio
import ssl
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any, Literal, NamedTuple

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field, IPvAnyAddress
from pydantic_settings import BaseSettings

SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
TOOLSET_LABEL = "mcp-toolsets/toolset"


class IndexSettings(BaseSettings):
    """Index configuration, validated from the environment."""

    public_url: str
    host: IPvAnyAddress = IPv4Address("127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)


class ToolsetService(NamedTuple):
    """A deployed toolset and its in-cluster base URL."""

    toolset: str
    base_url: str


class ToolsetEntry(BaseModel):
    """One deployed toolset in the directory.

    ``credential_headers`` names the per-user HTTP headers the toolset's
    tools read; clients should send those credentials only to this toolset's
    connection.
    """

    name: str
    url: str
    status: Literal["ok", "unreachable"]
    tools: list[str]
    credential_headers: list[str] = []


class Connection(BaseModel):
    """A langchain-mcp-adapters StreamableHttpConnection."""

    transport: Literal["streamable_http"] = "streamable_http"
    url: str


class Index(BaseModel):
    """Directory of every deployed toolset.

    ``connections`` is shaped so an agent can pass it straight to
    ``MultiServerMCPClient``; ``toolsets`` adds per-service status and tool
    names for humans.
    """

    connections: dict[str, Connection]
    toolsets: list[ToolsetEntry]


def toolset_services(service_list: dict[str, Any]) -> list[ToolsetService]:
    """Extract toolset services from a Kubernetes ServiceList payload."""
    services = []
    for item in service_list.get("items", []):
        metadata = item["metadata"]
        toolset = metadata.get("labels", {}).get(TOOLSET_LABEL)
        if not toolset:
            continue
        port = item["spec"]["ports"][0]["port"]
        services.append(ToolsetService(toolset, f"http://{metadata['name']}:{port}"))
    return sorted(services)


def kubernetes_ssl_context() -> ssl.SSLContext | bool:
    """Trust the cluster CA when running in a pod; default verification otherwise."""
    ca = SERVICE_ACCOUNT_DIR / "ca.crt"
    return ssl.create_default_context(cafile=str(ca)) if ca.exists() else True


async def fetch_toolset_services(client: httpx.AsyncClient) -> list[ToolsetService]:
    """List toolset Services in this pod's namespace via the Kubernetes API."""
    namespace = (SERVICE_ACCOUNT_DIR / "namespace").read_text().strip()
    token = (SERVICE_ACCOUNT_DIR / "token").read_text().strip()
    response = await client.get(
        f"https://kubernetes.default.svc/api/v1/namespaces/{namespace}/services",
        params={"labelSelector": TOOLSET_LABEL},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return toolset_services(response.json())


async def describe(
    client: httpx.AsyncClient, service: ToolsetService, public_url: str
) -> ToolsetEntry:
    """Build one directory entry, asking the toolset's /health for its tools."""
    url = f"{public_url}/{service.toolset}/mcp"
    try:
        response = await client.get(f"{service.base_url}/health")
        response.raise_for_status()
        health = response.json()
    except httpx.HTTPError:
        return ToolsetEntry(
            name=service.toolset, url=url, status="unreachable", tools=[]
        )
    return ToolsetEntry(
        name=service.toolset,
        url=url,
        status="ok",
        tools=health.get("tools", []),
        credential_headers=health.get("credential_headers", []),
    )


def build_app(public_url: str) -> FastAPI:
    """Build the index app: a toolset directory at ``/``, health at ``/health``."""
    base_url = public_url.rstrip("/")
    app = FastAPI(
        title="mcp-toolsets",
        description="Directory of every deployed MCP toolset service.",
    )

    @app.get("/")
    async def index() -> Index:
        async with httpx.AsyncClient(
            verify=kubernetes_ssl_context(), timeout=5.0
        ) as client:
            services = await fetch_toolset_services(client)
            entries = await asyncio.gather(
                *(describe(client, service, base_url) for service in services)
            )
        return Index(
            connections={entry.name: Connection(url=entry.url) for entry in entries},
            toolsets=list(entries),
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main() -> None:
    """Console entry point (``mcp-index``)."""
    settings = IndexSettings()
    app = build_app(settings.public_url)
    uvicorn.run(app, host=str(settings.host), port=settings.port)
