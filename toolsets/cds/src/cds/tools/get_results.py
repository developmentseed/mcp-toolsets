from typing import Any

from langchain_core.tools import tool

from ..client import make_client
from ._errors import classify_http_error, not_ready_error, transient_error
from ._retry import TRANSIENT_EXC, with_retry


@with_retry
async def _call(job_id: str) -> dict[str, Any]:
    async with make_client() as client:
        # Confirm the job is successful before fetching assets.
        status_resp = await client.get(f"/jobs/{job_id}")
        if status_resp.status_code >= 500:
            status_resp.raise_for_status()
        if status_resp.status_code != 200:
            return classify_http_error(status_resp)

        status: str = status_resp.json().get("status", "unknown")
        if status != "successful":
            return not_ready_error(job_id, status)

        results_resp = await client.get(f"/jobs/{job_id}/results")
        if results_resp.status_code >= 500:
            results_resp.raise_for_status()
        if results_resp.status_code != 200:
            return classify_http_error(results_resp)

    try:
        val = results_resp.json()["asset"]["value"]
        return {
            "href": val["href"],
            "content_type": val.get("type"),
            "size": val.get("file:size"),
            "checksum": val.get("file:checksum"),
        }
    except (KeyError, TypeError):
        return transient_error("Unexpected results shape from CDS API.")


@tool
async def get_results(job_id: str) -> dict[str, Any]:
    """Get the download link for a completed CDS job.

    Args:
        job_id: The job ID of a job with status "successful".

    Returns dict with href, content_type, size, checksum — or a structured error.
    The href is a public URL; no token needed to download the file.
    """
    try:
        return await _call(job_id)
    except TRANSIENT_EXC as exc:
        return transient_error(str(exc))
