import pytest

from mcp_cli.main import parse_headers, parse_tool_args


def test_parse_headers():
    assert parse_headers(None) is None
    assert parse_headers([]) is None
    assert parse_headers(["X-Demo-Token: secret", "Other:  spaced  "]) == {
        "X-Demo-Token": "secret",
        "Other": "spaced",
    }


@pytest.mark.parametrize("bad", ["no-separator", ": empty-name", "empty-value:"])
def test_parse_headers_rejects_malformed(bad):
    with pytest.raises(ValueError, match="Name: value"):
        parse_headers([bad])


def test_parse_tool_args():
    assert parse_tool_args(["query=era5", "limit=3", "flag=true"]) == {
        "query": "era5",
        "limit": 3,
        "flag": True,
    }
    with pytest.raises(ValueError, match="key=value"):
        parse_tool_args(["nope"])
