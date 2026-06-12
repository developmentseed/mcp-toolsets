from typing import Any

from langchain_core.tools import tool

from ..client import make_client
from ._errors import classify_http_error, transient_error
from ._retry import TRANSIENT_EXC, with_retry


@with_retry
async def _call() -> dict[str, Any]:
    async with make_client() as client:
        resp = await client.get("/jobs", params={"limit": 1})
        if resp.status_code >= 500:
            resp.raise_for_status()
    if resp.status_code == 200:
        return {"ok": True}
    return classify_http_error(resp)


@tool
async def check_credentials() -> dict[str, Any]:
    """Validate the calling user's CDS API key (the `x-cds-token` MCP header).

    Returns {"ok": True} on success or a structured error dict.
    """
    try:
        return await _call()
    except TRANSIENT_EXC as exc:
        return transient_error(str(exc))
