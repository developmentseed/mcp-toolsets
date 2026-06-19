"""Evaluation run configuration, validated from the environment or a .env file.

Mirrors ``mcp_agent.main.AgentSettings``: the Mistral key (used both to drive
the agent and to grade answers) comes from the environment, while the CLI
supplies the per-run knobs (URL, sheet id, filters).
"""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MCP_URL = "http://localhost:8000/mcp"
DEFAULT_MODEL = "mistral-small-latest"

# Same provider as the agent under test (user chose Mistral as the judge).
DEFAULT_JUDGE_MODEL = "mistral-small-latest"

# A case passes when the mean of its present (non-None) scores clears this,
# matching the gnw-evals default.
PASS_THRESHOLD = 0.7


class EvalSettings(BaseSettings):
    """Run configuration from the environment or a ``.env`` file.

    Only ``mistral_api_key`` is required; everything else has a default and is
    typically overridden by CLI options.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mistral_api_key: SecretStr
    mistral_model: str = DEFAULT_MODEL
    judge_model: str = DEFAULT_JUDGE_MODEL
    mcp_url: str = DEFAULT_MCP_URL
    # The eval-data spreadsheet (shared "anyone with the link can view"); read
    # via its CSV export URL, so no Google credentials are needed.
    spreadsheet_id: str | None = None
    spreadsheet_gid: int = Field(default=0, ge=0)
