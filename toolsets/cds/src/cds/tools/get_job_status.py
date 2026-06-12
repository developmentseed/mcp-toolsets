from typing import Any

from langchain_core.tools import tool

from ._client import get_client
from ._errors import classify_http_error, transient_error
from ._retry import TRANSIENT_EXC, with_retry


@with_retry
async def _call(job_id: str) -> dict[str, Any]:
    resp = await get_client().get(f"/jobs/{job_id}")
    if resp.status_code >= 500:
        resp.raise_for_status()
    if resp.status_code != 200:
        return classify_http_error(resp)

    data = resp.json()
    status: str = data.get("status", "unknown")
    return {
        "job_id": job_id,
        "status": status,
        "results_ready": status == "successful",
        "created": data.get("created"),
        "started": data.get("started"),
        "finished": data.get("finished"),
    }


@tool
async def get_job_status(job_id: str) -> dict[str, Any]:
    """Get the current status of a CDS job.

    Args:
        job_id: The job ID returned by submit_request.

    Returns dict with job_id, status, results_ready flag, and timestamps.
    """
    try:
        return await _call(job_id)
    except TRANSIENT_EXC as exc:
        return transient_error(str(exc))
