from typing import Any

from langchain_core.tools import tool

from ._client import get_client
from ._errors import classify_http_error, not_found_error, transient_error
from ._retry import TRANSIENT_EXC, with_retry


@with_retry
async def _call(dataset: str, partial_request: dict[str, Any]) -> dict[str, Any]:
    resp = await get_client().post(
        f"/processes/{dataset}/constraints",
        json={"inputs": partial_request},
    )
    if resp.status_code >= 500:
        resp.raise_for_status()
    if resp.status_code == 404:
        return not_found_error(f"Dataset {dataset!r} not found.")
    if resp.status_code != 200:
        return classify_http_error(resp)

    raw: dict[str, list[str]] = resp.json()
    # Omit parameters with empty lists — those are unconstrained (e.g. area)
    valid_values = {k: v for k, v in raw.items() if v}

    return {"dataset": dataset, "valid_values": valid_values}


@tool
async def apply_constraints(
    dataset: str, partial_request: dict[str, Any]
) -> dict[str, Any]:
    """Get valid parameter values for a CDS dataset given a partial request.

    Pass whatever parameters you already know (e.g. year and month) and receive
    back the valid values for all remaining parameters. Use this to verify that
    requested dates exist in the archive — especially for recent or current-year data.

    Args:
        dataset: Dataset identifier, e.g. "reanalysis-era5-land".
        partial_request: Partial request dict, e.g. {"year": "2026", "month": "05"}.

    Returns a dict with 'dataset' and 'valid_values' mapping each constrained
    parameter to its list of currently valid values.
    """
    try:
        return await _call(dataset, partial_request)
    except TRANSIENT_EXC as exc:
        return transient_error(str(exc))
