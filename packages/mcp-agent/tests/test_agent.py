import pytest
from pydantic import ValidationError

from mcp_agent.main import (
    AgentSettings,
    connect_error_hint,
    connections_from,
    credential_client_factory,
    credential_headers_from,
    first_leaf,
    health_url_for,
    user_credentials,
    with_credential_support,
)


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("PROVIDER_API_KEY", "sk-test")
    monkeypatch.setenv("PROVIDER_MODEL", "openai:gpt-4o-mini")
    settings = AgentSettings(_env_file=None)
    assert settings.provider_api_key.get_secret_value() == "sk-test"
    assert settings.provider_model == "openai:gpt-4o-mini"


def test_settings_from_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("PROVIDER_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PROVIDER_API_KEY=sk-dotenv\nPROVIDER_MODEL=openai:gpt-4o-mini\nUNRELATED=ignored\n"
    )
    settings = AgentSettings(_env_file=env_file)
    assert settings.provider_api_key.get_secret_value() == "sk-dotenv"
    assert settings.provider_model == "openai:gpt-4o-mini"


def test_settings_require_provider(monkeypatch):
    # Both PROVIDER_MODEL and PROVIDER_API_KEY are required — no default provider.
    monkeypatch.delenv("PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("PROVIDER_MODEL", raising=False)
    with pytest.raises(ValidationError):
        AgentSettings(_env_file=None)


def test_connections_from_index_payload():
    payload = {
        "connections": {
            "dataset-search": {
                "transport": "streamable_http",
                "url": "https://mcp.example.com/dataset-search/mcp",
            }
        },
        "toolsets": [],
    }
    assert (
        connections_from("https://mcp.example.com/", payload)
        == (payload["connections"])
    )


def test_connections_from_non_index_payload_wraps_url():
    expected = {
        "server": {"transport": "streamable_http", "url": "http://localhost:8000/mcp"}
    }
    assert connections_from("http://localhost:8000/mcp", None) == expected
    assert connections_from("http://localhost:8000/mcp", {"status": "ok"}) == expected


def test_credential_headers_from_index_payload():
    payload = {
        "connections": {},
        "toolsets": [
            {"name": "credential-demo", "credential_headers": ["X-Demo-Token"]},
            {"name": "dataset-search", "credential_headers": []},
            {"name": "hello"},
        ],
    }
    assert credential_headers_from(payload) == {
        "credential-demo": ["x-demo-token"],
        "dataset-search": [],
        "hello": [],
    }


def test_credential_headers_from_non_index_payload():
    assert credential_headers_from(None) is None
    assert credential_headers_from({"status": "ok"}) is None


async def test_credential_factory_injects_only_declared_headers():
    factory = credential_client_factory(["x-demo-token"])
    with user_credentials({"X-Demo-Token": "secret", "x-other-cred": "nope"}):
        client = factory(headers={"existing": "kept"})
    async with client:
        assert client.headers["x-demo-token"] == "secret"
        assert client.headers["existing"] == "kept"
        assert "x-other-cred" not in client.headers


async def test_credential_factory_without_declaration_sends_all():
    factory = credential_client_factory(None)
    with user_credentials({"x-demo-token": "secret", "x-other-cred": "yes"}):
        client = factory()
    async with client:
        assert client.headers["x-demo-token"] == "secret"
        assert client.headers["x-other-cred"] == "yes"


async def test_credential_factory_outside_context_injects_nothing():
    factory = credential_client_factory(["x-demo-token"])
    with user_credentials({"x-demo-token": "secret"}):
        pass  # context exited: credentials no longer available
    async with factory() as client:
        assert "x-demo-token" not in client.headers


def test_with_credential_support_wires_every_connection():
    connections = {
        "credential-demo": {"transport": "streamable_http", "url": "http://a/mcp"},
        "dataset-search": {"transport": "streamable_http", "url": "http://b/mcp"},
    }
    wired = with_credential_support(connections, {"credential-demo": ["x-demo-token"]})
    assert all(callable(c["httpx_client_factory"]) for c in wired.values())
    assert "httpx_client_factory" not in connections["credential-demo"]  # untouched


def test_connect_error_hint_only_for_urls_missing_mcp_path():
    assert "under /mcp" in connect_error_hint("http://localhost:8000")
    assert "under /mcp" in connect_error_hint("http://localhost:8000/")
    assert connect_error_hint("http://localhost:8000/mcp") == ""
    assert connect_error_hint("https://mcp.example.com/credential-demo/mcp/") == ""


def test_first_leaf_unwraps_nested_groups():
    error = ValueError("inner")
    group = ExceptionGroup("outer", [ExceptionGroup("nested", [error])])
    assert first_leaf(group) is error
    assert first_leaf(error) is error


def test_health_url_for():
    assert health_url_for("http://localhost:8000/mcp") == "http://localhost:8000/health"
    assert (
        health_url_for("https://mcp.example.com/credential-demo/mcp/")
        == "https://mcp.example.com/credential-demo/health"
    )
    assert health_url_for("https://mcp.example.com/") is None
