import pytest
from mcp_runtime.credentials import MissingCredentialError, header_context

from credential_demo.tools import DEMO_TOKEN_HEADER, whoami


def test_account_reported_with_credential():
    with header_context({DEMO_TOKEN_HEADER: "secret"}):
        result = whoami.invoke({})
    assert "belongs to account user-" in result["message"]
    assert result["account"].startswith("user-")
    assert result["account"] in result["message"]


def test_account_stable_per_user():
    with header_context({DEMO_TOKEN_HEADER: "secret"}):
        first, second = (whoami.invoke({}) for _ in range(2))
    with header_context({DEMO_TOKEN_HEADER: "other"}):
        other_user = whoami.invoke({})
    assert first == second
    assert first["account"] != other_user["account"]


def test_token_never_appears_in_the_result():
    with header_context({DEMO_TOKEN_HEADER: "secret"}):
        result = whoami.invoke({})
    assert "secret" not in str(result)


def test_missing_credential_names_the_header():
    with pytest.raises(MissingCredentialError, match=DEMO_TOKEN_HEADER):
        whoami.invoke({})
