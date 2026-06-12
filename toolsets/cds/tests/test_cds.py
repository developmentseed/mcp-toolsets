"""Unit tests for the CDS toolset (ported from cds-assistant)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from cds.tools import TOOLS
from cds.tools.apply_constraints import _call as _apply_call
from cds.tools.get_dataset_schema import _call as _schema_call
from cds.tools.get_dataset_schema import _parse_parameter
from cds.tools.search_datasets import _call as _search_call

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ERA5_PROCESS_RESPONSE = {
    "id": "reanalysis-era5-land",
    "inputs": {
        "variable": {
            "schema": {
                "type": "array",
                "items": {"enum": ["2m_temperature", "total_precipitation"]},
            }
        },
        "year": {"schema": {"type": "string", "enum": ["2020", "2024"]}},
        "month": {"schema": {"type": "string", "enum": ["01", "12"]}},
        "data_format": {"schema": {"type": "string", "enum": ["grib", "netcdf"]}},
        "area": {"schema": {"type": "array", "default": [90, -180, -90, 180]}},
        "download_format": {
            "schema": {
                "type": "string",
                "enum": ["zip", "unarchived"],
                "default": "unarchived",
            }
        },
    },
}

CONSTRAINTS_RESPONSE = {
    "variable": ["2m_temperature", "total_precipitation"],
    "day": ["01", "02", "28"],
    "time": ["00:00", "12:00"],
    "data_format": ["grib", "netcdf"],
    "area": [],  # unconstrained — should be filtered
    "download_format": ["unarchived", "zip"],
}

CATALOGUE_RESPONSE = {
    "results": [
        {"id": "reanalysis-era5-land", "title": "ERA5-Land hourly data"},
        {
            "id": "reanalysis-era5-pressure-levels",
            "title": "ERA5 hourly on pressure levels",
        },
    ]
}


def _mock_client(method: str, response: httpx.Response) -> MagicMock:
    client = MagicMock()
    setattr(client, method, AsyncMock(return_value=response))
    return client


# ---------------------------------------------------------------------------
# TOOLS export
# ---------------------------------------------------------------------------


def test_tools_exported() -> None:
    names = {tool.name for tool in TOOLS}
    assert names == {
        "search_datasets",
        "get_dataset_schema",
        "apply_constraints",
        "submit_request",
        "get_job_status",
        "get_results",
        "list_jobs",
        "check_credentials",
    }


# ---------------------------------------------------------------------------
# _parse_parameter (pure function — no mocking needed)
# ---------------------------------------------------------------------------


def test_parse_string_field_with_enum() -> None:
    spec = {"schema": {"type": "string", "enum": ["grib", "netcdf"]}}
    result = _parse_parameter(spec)
    assert result == {"type": "string", "required": True, "values": ["grib", "netcdf"]}


def test_parse_array_field_with_items_enum() -> None:
    spec = {"schema": {"type": "array", "items": {"enum": ["00:00", "06:00", "12:00"]}}}
    result = _parse_parameter(spec)
    assert result == {
        "type": "array",
        "required": True,
        "values": ["00:00", "06:00", "12:00"],
    }


def test_parse_optional_field_with_default_only() -> None:
    spec = {"schema": {"type": "array", "default": [90, -180, -90, 180]}}
    result = _parse_parameter(spec)
    assert result["required"] is False
    assert result["default"] == [90, -180, -90, 180]
    assert "values" not in result


def test_parse_optional_field_with_default_and_enum() -> None:
    spec = {
        "schema": {
            "type": "string",
            "enum": ["zip", "unarchived"],
            "default": "unarchived",
        }
    }
    result = _parse_parameter(spec)
    assert result["required"] is False
    assert result["values"] == ["zip", "unarchived"]
    assert result["default"] == "unarchived"


# ---------------------------------------------------------------------------
# get_dataset_schema
# ---------------------------------------------------------------------------


async def test_get_dataset_schema_parses_all_fields() -> None:
    client = _mock_client("get", httpx.Response(200, json=ERA5_PROCESS_RESPONSE))

    with patch("cds.tools.get_dataset_schema.get_client", return_value=client):
        result = await _schema_call("reanalysis-era5-land")

    assert result["dataset"] == "reanalysis-era5-land"
    params = result["parameters"]

    assert params["variable"] == {
        "type": "array",
        "required": True,
        "values": ["2m_temperature", "total_precipitation"],
    }
    assert params["year"] == {
        "type": "string",
        "required": True,
        "values": ["2020", "2024"],
    }
    assert params["area"]["required"] is False
    assert params["area"]["default"] == [90, -180, -90, 180]
    assert params["download_format"]["required"] is False
    assert params["download_format"]["values"] == ["zip", "unarchived"]


async def test_get_dataset_schema_not_found() -> None:
    client = _mock_client("get", httpx.Response(404, json={"detail": "not found"}))

    with patch("cds.tools.get_dataset_schema.get_client", return_value=client):
        result = await _schema_call("bad-dataset")

    assert result["error"] == "not_found"
    assert "bad-dataset" in result["detail"]


# ---------------------------------------------------------------------------
# apply_constraints
# ---------------------------------------------------------------------------


async def test_apply_constraints_filters_empty_lists() -> None:
    client = _mock_client("post", httpx.Response(200, json=CONSTRAINTS_RESPONSE))

    with patch("cds.tools.apply_constraints.get_client", return_value=client):
        result = await _apply_call(
            "reanalysis-era5-land", {"year": "2024", "month": "01"}
        )

    assert result["dataset"] == "reanalysis-era5-land"
    assert "area" not in result["valid_values"]  # empty list removed
    assert result["valid_values"]["day"] == ["01", "02", "28"]


async def test_apply_constraints_sends_inputs_wrapper() -> None:
    client = _mock_client("post", httpx.Response(200, json=CONSTRAINTS_RESPONSE))

    with patch("cds.tools.apply_constraints.get_client", return_value=client):
        await _apply_call("reanalysis-era5-land", {"year": "2024", "month": "01"})

    _, call_kwargs = client.post.call_args
    assert call_kwargs["json"] == {"inputs": {"year": "2024", "month": "01"}}


async def test_apply_constraints_not_found() -> None:
    client = _mock_client("post", httpx.Response(404, json={"detail": "not found"}))

    with patch("cds.tools.apply_constraints.get_client", return_value=client):
        result = await _apply_call("bad-dataset", {})

    assert result["error"] == "not_found"


# ---------------------------------------------------------------------------
# search_datasets
# ---------------------------------------------------------------------------


async def test_search_datasets_returns_id_and_title() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = CATALOGUE_RESPONSE

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("cds.tools.search_datasets.httpx.AsyncClient", return_value=mock_client):
        results = await _search_call("ERA5")

    assert len(results) == 2
    assert results[0] == {
        "id": "reanalysis-era5-land",
        "title": "ERA5-Land hourly data",
    }
    assert results[1]["id"] == "reanalysis-era5-pressure-levels"


async def test_search_datasets_passes_q_param() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("cds.tools.search_datasets.httpx.AsyncClient", return_value=mock_client):
        await _search_call("sea surface temperature")

    _, call_kwargs = mock_client.get.call_args
    assert call_kwargs["params"]["q"] == "sea surface temperature"
    assert call_kwargs["params"]["limit"] == 10


# ---------------------------------------------------------------------------
# _parse_parameter — new schema types
# ---------------------------------------------------------------------------


def test_parse_integer_field_with_range() -> None:
    spec = {"schema": {"type": "integer", "minimum": 1, "maximum": 1000}}
    result = _parse_parameter(spec)
    assert result["type"] == "integer"
    assert result["required"] is True
    assert result["minimum"] == 1
    assert result["maximum"] == 1000
    assert "values" not in result


def test_parse_number_field_no_range() -> None:
    spec = {"schema": {"type": "number"}}
    result = _parse_parameter(spec)
    assert result["type"] == "number"
    assert result["required"] is True
    assert "minimum" not in result
    assert "maximum" not in result


def test_parse_boolean_field() -> None:
    spec = {"schema": {"type": "boolean"}}
    result = _parse_parameter(spec)
    assert result["type"] == "boolean"
    assert result["required"] is True
    assert "values" not in result


def test_parse_one_of_schema() -> None:
    spec = {
        "schema": {
            "oneOf": [
                {"type": "string", "enum": ["grib"]},
                {"type": "string", "enum": ["netcdf", "netcdf4"]},
            ]
        }
    }
    result = _parse_parameter(spec)
    assert result["type"] == "string"
    assert set(result["values"]) == {"grib", "netcdf", "netcdf4"}


def test_parse_const_value() -> None:
    spec = {"schema": {"type": "string", "const": "netcdf"}}
    result = _parse_parameter(spec)
    assert result["values"] == ["netcdf"]
    assert result["required"] is True


def test_parse_spec_with_title_and_description() -> None:
    spec = {
        "title": "Output format",
        "description": "Format of the downloaded file.",
        "schema": {"type": "string", "enum": ["grib", "netcdf"]},
    }
    result = _parse_parameter(spec)
    assert result["title"] == "Output format"
    assert result["description"] == "Format of the downloaded file."
    assert result["values"] == ["grib", "netcdf"]


def test_parse_min_occurs_zero_marks_optional() -> None:
    spec = {"minOccurs": 0, "schema": {"type": "string", "enum": ["a", "b"]}}
    result = _parse_parameter(spec)
    assert result["required"] is False
    assert result["values"] == ["a", "b"]


def test_parse_no_schema_key() -> None:
    spec = {"title": "Mystery field"}
    result = _parse_parameter(spec)
    assert result["type"] == "unknown"
    assert result["required"] is True
    assert result["title"] == "Mystery field"
