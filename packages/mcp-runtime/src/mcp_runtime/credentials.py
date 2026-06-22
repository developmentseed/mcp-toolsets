"""Read per-user credentials from the calling MCP request's HTTP headers.

Tools that act on a user's behalf (e.g. downloading from a source that needs
the user's API key) must not bake secrets into the deployment. Instead the
MCP client sends them as HTTP headers on every call — `MultiServerMCPClient`
takes a ``headers`` dict per connection, ``mcp-cli`` takes ``--header`` — and
the tool reads them at call time with :func:`credential_from_header`.

The credential rides the transport, so it never appears in the model context,
tool schemas, chat history or traces. Works with the stateless streamable
HTTP runtime (every tool call is its own request, carrying its own headers)
and from both sync and async tools.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

from mcp.server.lowlevel.server import request_ctx
from mcp.shared.context import RequestContext
from starlette.requests import Request


class MissingCredentialError(Exception):
    """A required credential header was absent from the calling request."""

    def __init__(self, header: str) -> None:
        super().__init__(
            f"missing credential: send the {header!r} HTTP header with your "
            f"MCP requests (MultiServerMCPClient connections take a 'headers' "
            f"dict; mcp-cli takes --header)"
        )
        self.header = header


def credential_from_header(header: str) -> str:
    """Return the named header from the MCP request that invoked this tool.

    Raises :class:`MissingCredentialError` if the header is absent or the
    tool was not invoked over HTTP (e.g. called directly in tests).
    """
    try:
        request = request_ctx.get().request
    except LookupError:
        request = None
    value = request.headers.get(header) if isinstance(request, Request) else None
    if not value:
        raise MissingCredentialError(header)
    return value


@contextmanager
def header_context(headers: dict[str, str]) -> Iterator[None]:
    """Run as if inside an MCP request carrying ``headers`` (test support).

    Lets toolset tests exercise credential-reading tools without a server:

        with header_context({"x-demo-token": "secret"}):
            my_tool.invoke({...})
    """
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [
            (name.lower().encode(), value.encode()) for name, value in headers.items()
        ],
    }
    context: RequestContext[Any, Any, Any] = RequestContext(
        request_id=0,
        meta=None,
        session=cast(Any, None),
        lifespan_context=None,
        request=Request(scope),
    )
    token = request_ctx.set(context)
    try:
        yield
    finally:
        request_ctx.reset(token)
