from typing import Any

from langchain_core.tools import tool

from ..client import make_client
from ._errors import classify_http_error, transient_error
from ._retry import TRANSIENT_EXC, with_retry


@with_retry
async def _call(status: list[str] | None, limit: int) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status  # httpx repeats the key for each value

    async with make_client() as client:
        resp = await client.get("/jobs", params=params)
        if resp.status_code >= 500:
            resp.raise_for_status()
    if resp.status_code != 200:
        return classify_http_error(resp)

    data = resp.json()
    jobs = [
        {
            "job_id": j.get("jobID") or j.get("job_id"),
            "dataset": j.get("processID"),
            "status": j.get("status"),
            "results_ready": j.get("status") == "successful",
            "created": j.get("created"),
            "finished": j.get("finished"),
        }
        for j in data.get("jobs", [])
    ]

    result: dict[str, Any] = {"jobs": jobs, "count": len(jobs)}
    next_link = next(
        (lnk["href"] for lnk in data.get("links", []) if lnk.get("rel") == "next"),
        None,
    )
    if next_link:
        result["next"] = next_link

    return result


@tool
async def list_jobs(
    status: list[str] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List CDS jobs, optionally filtered by status.

    Args:
        status: One or more statuses to filter by. Valid values: "accepted",
            "running", "successful", "failed". Omit to return all statuses.
        limit: Maximum number of jobs to return (default 100).

    Returns dict with a "jobs" list and "count". Includes "next" cursor URL when
    more results are available.
    """
    try:
        return await _call(status, limit)
    except TRANSIENT_EXC as exc:
        return transient_error(str(exc))
