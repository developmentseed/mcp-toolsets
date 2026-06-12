from typing import Any

from langchain_core.tools import tool

from ..client import make_client
from ._errors import classify_http_error, classify_submit_failure, transient_error
from ._retry import TRANSIENT_EXC, with_retry


def _failure_message(data: dict[str, Any]) -> str:
    meta = data.get("metadata") or {}
    results = meta.get("results") or {}
    return (
        results.get("traceback")
        or results.get("message")
        or data.get("message")
        or "Unknown failure reason."
    )


@with_retry
async def _call(dataset: str, request: dict[str, Any]) -> dict[str, Any]:
    async with make_client() as client:
        resp = await client.post(
            f"/processes/{dataset}/execution",
            json={"inputs": request},
        )
        if resp.status_code >= 500:
            resp.raise_for_status()
    if resp.status_code not in (200, 201):
        return classify_http_error(resp, dataset)

    data = resp.json()
    status: str = data.get("status", "accepted")

    if status == "failed":
        return classify_submit_failure(_failure_message(data), dataset)

    return {
        "job_id": data.get("jobID") or data.get("job_id") or "",
        "status": status,
    }


@tool
async def submit_request(dataset: str, request: dict[str, Any]) -> dict[str, Any]:
    """Submit a data request to the CDS.

    Args:
        dataset: Dataset identifier, e.g. "reanalysis-era5-land".
        request: Bare request parameters dict — do NOT wrap in "inputs", that is added internally.

    Returns dict with job_id and status, or a structured error dict.
    """
    try:
        return await _call(dataset, request)
    except TRANSIENT_EXC as exc:
        return transient_error(str(exc))
