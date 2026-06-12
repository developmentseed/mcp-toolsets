"""LangChain tools demonstrating per-user credentials.

Example of a credential-using toolset: the user's token arrives as an HTTP
header on each MCP call (never as a tool argument, so the model and the chat
history never see it) and is read with
``mcp_runtime.credentials.credential_from_header``. The "account lookup" is
stubbed — a real implementation would pass the token to an upstream API.
"""

import hashlib
import logging
from typing import Any

from langchain_core.tools import tool

from mcp_runtime.credentials import MissingCredentialError, credential_from_header

logger = logging.getLogger(__name__)

DEMO_TOKEN_HEADER = "x-demo-token"  # noqa: S105 - the header's name, not a secret


@tool
def whoami() -> dict[str, Any]:
    """Report which account the calling user's credential belongs to.

    Requires the caller's token in the `x-demo-token` HTTP header of the MCP
    request — ask the user to configure it if missing; it cannot be passed
    as an argument.
    """
    try:
        token = credential_from_header(DEMO_TOKEN_HEADER)
    except MissingCredentialError:
        logger.info("whoami: no %s credential on this request", DEMO_TOKEN_HEADER)
        raise
    # Log presence only — never the value.
    logger.info(
        "whoami: %s credential present (%d chars)", DEMO_TOKEN_HEADER, len(token)
    )
    # Stub: derive a stable account id instead of calling an upstream API.
    account = hashlib.sha256(token.encode()).hexdigest()[:8]
    return {"account": f"user-{account}", "status": "ok"}


TOOLS = [whoami]

# Advertised via /health and the index: clients send this credential to this
# toolset's connection only, never to unrelated toolsets.
CREDENTIAL_HEADERS = [DEMO_TOKEN_HEADER]
