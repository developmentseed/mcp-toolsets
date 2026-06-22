import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import mcp_runtime.index
from mcp_runtime.index import (
    IndexSettings,
    ToolsetService,
    build_app,
    toolset_services,
)


def service_item(name: str, toolset: str | None, port: int = 8000) -> dict:
    labels = {"mcp-toolsets/toolset": toolset} if toolset else {}
    return {
        "metadata": {"name": name, "labels": labels},
        "spec": {"ports": [{"port": port}]},
    }


def test_toolset_services_parses_and_sorts():
    payload = {
        "items": [
            service_item("mcp-hello", "hello", port=9000),
            service_item("mcp-dataset-search", "dataset-search"),
        ]
    }
    assert toolset_services(payload) == [
        ToolsetService("dataset-search", "http://mcp-dataset-search:8000"),
        ToolsetService("hello", "http://mcp-hello:9000"),
    ]


def test_toolset_services_skips_unlabelled():
    payload = {"items": [service_item("mcp-index", None)]}
    assert toolset_services(payload) == []


def test_settings_require_public_url(monkeypatch):
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    with pytest.raises(ValidationError):
        IndexSettings()


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://mcp.example.com")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9000")
    settings = IndexSettings()
    assert settings.public_url == "https://mcp.example.com"
    assert str(settings.host) == "0.0.0.0"
    assert settings.port == 9000


def test_health_route():
    client = TestClient(build_app("https://mcp.example.com"))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_route(monkeypatch):
    async def fake_fetch(client):
        return [ToolsetService("dataset-search", "http://mcp-dataset-search:8000")]

    async def fake_describe(client, service, public_url):
        return mcp_runtime.index.ToolsetEntry(
            name=service.toolset,
            url=f"{public_url}/{service.toolset}/mcp",
            status="ok",
            tools=["search_datasets"],
            credential_headers=["x-demo-token"],
        )

    monkeypatch.setattr(mcp_runtime.index, "fetch_toolset_services", fake_fetch)
    monkeypatch.setattr(mcp_runtime.index, "describe", fake_describe)

    client = TestClient(build_app("https://mcp.example.com/"))
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "connections": {
            "dataset-search": {
                "transport": "streamable_http",
                "url": "https://mcp.example.com/dataset-search/mcp",
            }
        },
        "toolsets": [
            {
                "name": "dataset-search",
                "url": "https://mcp.example.com/dataset-search/mcp",
                "status": "ok",
                "tools": ["search_datasets"],
                "credential_headers": ["x-demo-token"],
            }
        ],
    }
