"""Upstream ``to_fastmcp`` plus an output schema from the return annotation.

langchain-mcp-adapters' ``to_fastmcp`` discards the return annotation, so
FastMCP never advertises an ``outputSchema`` and results reach clients as
JSON text only. This wrapper derives the output model from the annotation —
a TypedDict/BaseModel, or a union of them, with a required str ``message``
on at least one arm (the :mod:`mcp_runtime.tool_result` contract) — so
results also travel as ``structuredContent``. Any other annotation raises at
conversion, aborting ``build_server``: FastMCP would wrap such values in
``{"result": ...}`` or the schema would guarantee nothing.

FastMCP validates every returned dict against the model; undeclared keys are
dropped, so the annotation is the complete list of keys a client can see.
"""

from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints, is_typeddict

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import to_fastmcp as _to_fastmcp
from mcp.server.fastmcp.tools import Tool as FastMCPTool
from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata
from pydantic import BaseModel, RootModel


def _return_annotation(tool: BaseTool) -> Any:
    """The return annotation of the function behind a LangChain tool, if any."""
    fn = getattr(tool, "coroutine", None) or getattr(tool, "func", None)
    if fn is None:
        return None
    return get_type_hints(fn).get("return")


def _arms(annotation: Any) -> tuple[Any, ...]:
    """The annotation's union members, or the annotation itself."""
    if get_origin(annotation) in (Union, UnionType):
        return get_args(annotation)
    return (annotation,)


def _structured_dict(arm: Any) -> bool:
    """Whether one annotation arm maps 1:1 onto a structuredContent object."""
    return is_typeddict(arm) or (isinstance(arm, type) and issubclass(arm, BaseModel))


def _resolve(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """A schema node with its top-level ``$ref`` resolved against ``$defs``."""
    reference = schema.get("$ref", "")
    if reference.startswith("#/$defs/"):
        return defs.get(reference.removeprefix("#/$defs/"), {})
    return schema


def _shape_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """The advertised schema, object-rooted as MCP clients expect.

    ``RootModel`` schemas root at a ``$ref`` (single model) or an ``anyOf``
    (union): inline the former, stamp ``"type": "object"`` on the latter.
    """
    defs = dict(schema.get("$defs", {}))
    if schema.get("$ref", "").startswith("#/$defs/"):
        inlined = dict(_resolve(schema, defs))
        defs.pop(schema["$ref"].removeprefix("#/$defs/"))
        if defs:
            inlined["$defs"] = defs
        return inlined
    if "anyOf" in schema:
        return {"type": "object", "anyOf": schema["anyOf"], "$defs": defs}
    return schema


def _offers_message(schema: dict[str, Any]) -> bool:
    """Whether some arm of the schema requires a str ``message`` property."""
    defs: dict[str, Any] = schema.get("$defs", {})
    arms = [_resolve(arm, defs) for arm in schema.get("anyOf", [schema])]
    return any(
        arm.get("properties", {}).get("message", {}).get("type") == "string"
        and "message" in arm.get("required", [])
        for arm in arms
    )


def to_fastmcp(tool: BaseTool) -> FastMCPTool:
    """Convert a LangChain tool to FastMCP, deriving its output schema.

    Raises ``RuntimeError`` (naming the tool) when the return annotation does
    not follow the ToolResult contract — see the module docstring.
    """
    converted = _to_fastmcp(tool)
    annotation = _return_annotation(tool)
    if annotation is None or not all(
        _structured_dict(arm) for arm in _arms(annotation)
    ):
        raise RuntimeError(
            f"tool {tool.name!r} needs a ToolResult return annotation "
            f"(a TypedDict/BaseModel or a union of them; got {annotation!r}) "
            "— see mcp_runtime.tool_result"
        )
    model: type[BaseModel] = RootModel[annotation]  # type: ignore[valid-type]
    schema = _shape_schema(model.model_json_schema())
    if not _offers_message(schema):
        raise RuntimeError(
            f"tool {tool.name!r} does not follow the ToolResult contract: no arm "
            "of its return annotation has a required str 'message' property"
        )
    converted.fn_metadata = FuncMetadata(
        arg_model=converted.fn_metadata.arg_model,
        output_model=model,
        output_schema=schema,
        wrap_output=False,
    )
    return converted
