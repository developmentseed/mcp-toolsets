import httpx

from ..client import make_client

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = make_client()
    return _client
