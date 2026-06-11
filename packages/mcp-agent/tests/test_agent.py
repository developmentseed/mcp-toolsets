import pytest
from pydantic import ValidationError

from mcp_agent.main import AgentSettings, connections_from


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "sk-test")
    settings = AgentSettings(_env_file=None)
    assert settings.mistral_api_key.get_secret_value() == "sk-test"


def test_settings_from_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("MISTRAL_API_KEY=sk-dotenv\nUNRELATED=ignored\n")
    settings = AgentSettings(_env_file=env_file)
    assert settings.mistral_api_key.get_secret_value() == "sk-dotenv"


def test_settings_require_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
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
