import httpx

from mcp_runtime.credentials import credential_from_header

from .settings import settings

CDS_TOKEN_HEADER = "x-cds-token"  # noqa: S105 - the header's name, not a secret


def make_client() -> httpx.AsyncClient:
    """A retrieve-API client authenticated as the calling user.

    Reads the user's CDS key from the `x-cds-token` MCP request header,
    raising MissingCredentialError (which tells the caller how to supply it)
    when absent. Created per tool call and closed with it (`async with`), so
    one user's auth — or any other client state — can never leak into
    another user's requests.
    """
    return httpx.AsyncClient(
        base_url=settings.cds_api_url,
        headers={
            "PRIVATE-TOKEN": credential_from_header(CDS_TOKEN_HEADER),
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
    )
