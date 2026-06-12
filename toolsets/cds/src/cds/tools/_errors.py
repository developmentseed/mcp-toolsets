from typing import Any

import httpx


def auth_error(detail: str = "Invalid or missing API key.") -> dict[str, Any]:
    return {"error": "auth", "detail": detail}


def bad_request_error(detail: str) -> dict[str, Any]:
    return {"error": "bad_request", "detail": detail}


def licence_error(dataset: str = "") -> dict[str, Any]:
    if dataset:
        url = f"https://cds.climate.copernicus.eu/datasets/{dataset}"
        detail = f"Dataset licence not accepted. Accept the terms at {url} then retry."
    else:
        detail = (
            "Dataset licence not accepted. "
            "Visit the dataset page on CDS and accept the terms before retrying."
        )
    return {"error": "licence", "detail": detail}


def queue_limit_error() -> dict[str, Any]:
    return {
        "error": "queue_limit",
        "detail": (
            "Concurrent queued-job limit reached. Wait for existing jobs to complete."
        ),
    }


def not_found_error(detail: str) -> dict[str, Any]:
    return {"error": "not_found", "detail": detail}


def not_ready_error(job_id: str, status: str) -> dict[str, Any]:
    return {
        "error": "not_ready",
        "detail": (
            f"Job {job_id!r} is not yet successful (status: {status!r}). "
            "Poll again later."
        ),
    }


def transient_error(detail: str) -> dict[str, Any]:
    return {"error": "transient", "detail": detail}


def classify_submit_failure(message: str, dataset: str = "") -> dict[str, Any]:
    """Map a failed-job traceback/message to the appropriate error code."""
    lower = message.lower()
    if "licence" in lower or "license" in lower or "terms" in lower:
        return licence_error(dataset)
    if "queue" in lower:
        return queue_limit_error()
    return bad_request_error(message)


def classify_http_error(resp: httpx.Response, dataset: str = "") -> dict[str, Any]:
    if resp.status_code == 401:
        return auth_error()
    try:
        body: Any = resp.json()
        detail: Any = body.get("detail", resp.text)
    except Exception:
        body = {}
        detail = resp.text
    if resp.status_code == 403:
        detail_str = str(detail).lower()
        if any(w in detail_str for w in ("licence", "license", "terms")):
            return licence_error(dataset)
        return auth_error(str(detail))
    if resp.status_code in (400, 422):
        return bad_request_error(str(detail))
    return transient_error(f"HTTP {resp.status_code}: {str(detail)[:200]}")
