import pytest

from mcp_runtime.credentials import (
    MissingCredentialError,
    credential_from_header,
    header_context,
)


def test_reads_header_case_insensitively():
    with header_context({"X-Demo-Token": "secret"}):
        assert credential_from_header("x-demo-token") == "secret"
        assert credential_from_header("X-Demo-Token") == "secret"


def test_missing_header_names_it_in_the_error():
    with header_context({"other": "value"}):
        with pytest.raises(MissingCredentialError, match="x-demo-token"):
            credential_from_header("x-demo-token")


def test_outside_a_request_raises():
    with pytest.raises(MissingCredentialError, match="x-demo-token"):
        credential_from_header("x-demo-token")


def test_header_context_resets():
    with header_context({"x-demo-token": "secret"}):
        credential_from_header("x-demo-token")
    with pytest.raises(MissingCredentialError):
        credential_from_header("x-demo-token")
