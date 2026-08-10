"""Tests for duckdb-analyst.

These hit the real network — DuckDB's own httpfs/spatial/stac extensions
have no mockable transport the way `httpx.MockTransport` covers
`stac-explorer`. Fixtures are picked to be small and stable: a single ad hoc
parquet file DuckDB's own docs use as a demo (~500 bytes), and small,
filtered queries against the curated views (parquet row-group pruning means
these don't pull the whole multi-hundred-MB dataset over the wire).

The security regression suite is the important part: every case there must
come back as a `ToolError`, never rows.
"""

from mcp_runtime.tool_result import is_error

from duckdb_analyst.tools import chart, list_sources, query

# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_list_sources_covers_every_dataset_family():
    result = list_sources.invoke({})
    names = {source["name"] for source in result["sources"]}
    assert {
        "overture_divisions",
        "overture_places",
        "natural_earth_countries",
        "natural_earth_places",
        "STAC_Search",
    } <= names
    for source in result["sources"]:
        assert source["description"]
        assert source["example_sql"]


def test_list_sources_flags_chart_friendly_columns():
    result = list_sources.invoke({})
    divisions = next(s for s in result["sources"] if s["name"] == "overture_divisions")
    country_column = next(c for c in divisions["columns"] if c["name"] == "country")
    assert "x" in country_column["good_for"] or "color" in country_column["good_for"]


async def test_query_against_curated_view():
    result = await query.ainvoke(
        {
            "sql": (
                "SELECT primary_name, country FROM overture_divisions "
                "WHERE subtype = 'country' AND primary_name IS NOT NULL"
            ),
            "limit": 5,
        }
    )
    assert not is_error(result)
    assert 0 < len(result["rows"]) <= 5
    assert result["row_count"] == len(result["rows"])
    assert "primary_name" in result["rows"][0]


async def test_query_against_ad_hoc_public_parquet_url():
    result = await query.ainvoke(
        {
            "sql": "SELECT * FROM read_parquet('https://duckdb.org/data/holdings.parquet')"
        }
    )
    assert not is_error(result)
    assert len(result["rows"]) > 0


async def test_query_enforces_hard_row_cap_server_side():
    result = await query.ainvoke(
        {
            "sql": "SELECT * FROM range(100000) AS t(n)",
            "limit": 1_000_000,  # above MAX_ROW_LIMIT
        }
    )
    assert not is_error(result)
    assert result["row_count"] <= 10_000


async def test_chart_fills_in_data_values_and_preserves_spec():
    # A LIMIT-bounded, single-file-ish query (like the curated-view query
    # test above) rather than an unfiltered GROUP BY: aggregating across the
    # whole multi-GB overture_divisions view would need to scan every row
    # group instead of stopping early, and blow the 30s query timeout.
    spec = {
        "mark": "bar",
        "encoding": {"x": {"field": "primary_name"}, "y": {"field": "country"}},
    }
    result = await chart.ainvoke(
        {
            "sql": (
                "SELECT primary_name, country FROM overture_divisions "
                "WHERE subtype = 'country' AND primary_name IS NOT NULL"
            ),
            "spec": spec,
            "limit": 10,
        }
    )
    assert not is_error(result)
    assert result["spec"]["mark"] == "bar"
    assert result["spec"]["encoding"] == spec["encoding"]
    assert len(result["spec"]["data"]["values"]) <= 10


# ---------------------------------------------------------------------------
# Security regression suite: every one of these must be rejected, never
# silently succeed.
# ---------------------------------------------------------------------------


async def test_rejects_local_file_read_via_read_text_etc_passwd():
    result = await query.ainvoke({"sql": "SELECT * FROM read_text('/etc/passwd')"})
    assert is_error(result)


async def test_rejects_local_file_read_via_read_text_proc_environ():
    result = await query.ainvoke(
        {"sql": "SELECT * FROM read_text('/proc/self/environ')"}
    )
    assert is_error(result)


async def test_rejects_multiple_statements():
    result = await query.ainvoke({"sql": "SELECT 1; ATTACH ':memory:' AS x"})
    assert is_error(result)


async def test_rejects_install():
    result = await query.ainvoke({"sql": "INSTALL icu"})
    assert is_error(result)


async def test_rejects_attempt_to_loosen_locked_configuration():
    result = await query.ainvoke({"sql": "SET enable_external_access = true"})
    assert is_error(result)


async def test_rejects_pragma():
    result = await query.ainvoke({"sql": "PRAGMA database_list"})
    assert is_error(result)


async def test_rejects_duckdb_secrets():
    result = await query.ainvoke({"sql": "SELECT * FROM duckdb_secrets()"})
    assert is_error(result)
