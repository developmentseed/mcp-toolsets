from collections.abc import Callable
from typing import Any, TypeVar

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Exceptions that warrant automatic backoff retry.
# 5xx errors must be raised explicitly via raise_for_status() to trigger this.
TRANSIENT_EXC = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.HTTPStatusError,
)

_F = TypeVar("_F", bound=Callable[..., Any])

_retry = retry(
    retry=retry_if_exception_type(TRANSIENT_EXC),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)


def with_retry(fn: _F) -> _F:
    """Typed wrapper around tenacity retry so decorated functions keep their signature."""
    return _retry(fn)
