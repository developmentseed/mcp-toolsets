from typing import Any

from langchain_core.tools import tool

from ._client import get_client
from ._errors import classify_http_error, not_found_error, transient_error
from ._retry import TRANSIENT_EXC, with_retry


def _extract_enum(schema: dict[str, Any]) -> list[Any] | None:
    """Return enum values from a schema dict, handling const and items.enum."""
    if "const" in schema:
        return [schema["const"]]
    if "enum" in schema:
        enum_vals = schema["enum"]
        return enum_vals if isinstance(enum_vals, list) else [enum_vals]
    if schema.get("type") == "array":
        items = schema.get("items", {})
        if isinstance(items, dict) and "enum" in items:
            items_enum = items["enum"]
            return items_enum if isinstance(items_enum, list) else [items_enum]
    return None


def _parse_parameter(spec: dict[str, Any]) -> dict[str, Any]:
    if "schema" not in spec:
        result: dict[str, Any] = {
            "type": "unknown",
            "required": spec.get("minOccurs", 1) != 0,
        }
        if spec.get("title"):
            result["title"] = spec["title"]
        if spec.get("description"):
            result["description"] = spec["description"]
        return result

    schema = spec.get("schema", {})

    # Resolve oneOf / anyOf: union all enum values, take type from first branch
    field_type: str | None = None
    union_values: list[Any] = []
    for composite_key in ("oneOf", "anyOf"):
        if composite_key in schema:
            for branch in schema[composite_key]:
                if field_type is None:
                    field_type = branch.get("type")
                vals = _extract_enum(branch)
                if vals:
                    for v in vals:
                        if v not in union_values:
                            union_values.append(v)
            break

    if field_type is None:
        field_type = schema.get("type", "string")

    default = schema.get("default")
    min_occurs = spec.get("minOccurs", 1)
    required = (default is None) and (min_occurs != 0)

    result = {"type": field_type, "required": required}
    if default is not None:
        result["default"] = default
    if spec.get("title"):
        result["title"] = spec["title"]
    if spec.get("description"):
        result["description"] = spec["description"]

    # Enum / values
    if union_values:
        result["values"] = union_values
    else:
        vals = _extract_enum(schema)
        if vals is not None:
            result["values"] = vals
        elif field_type in ("integer", "number"):
            if "minimum" in schema:
                result["minimum"] = schema["minimum"]
            if "maximum" in schema:
                result["maximum"] = schema["maximum"]

    return result


@with_retry
async def _call(dataset: str) -> dict[str, Any]:
    resp = await get_client().get(f"/processes/{dataset}")
    if resp.status_code >= 500:
        resp.raise_for_status()
    if resp.status_code == 404:
        return not_found_error(f"Dataset {dataset!r} not found.")
    if resp.status_code != 200:
        return classify_http_error(resp)

    data = resp.json()
    raw_inputs: dict[str, Any] = data.get("inputs", {})
    parameters = {name: _parse_parameter(spec) for name, spec in raw_inputs.items()}

    return {"dataset": dataset, "parameters": parameters}


@tool
async def get_dataset_schema(dataset: str) -> dict[str, Any]:
    """Get the input schema for a CDS dataset: required parameters, valid values, and types.

    Args:
        dataset: Dataset identifier, e.g. "reanalysis-era5-land".

    Returns a dict with 'dataset' and 'parameters' mapping each field to its type,
    required flag, valid values list, and default (if optional).
    Always call this before submit_request to know what parameters are needed.
    """
    try:
        return await _call(dataset)
    except TRANSIENT_EXC as exc:
        return transient_error(str(exc))
