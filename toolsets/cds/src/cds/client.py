import httpx

from .settings import settings


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.cds_api_url,
        headers={
            "PRIVATE-TOKEN": settings.cds_api_key,
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
    )
