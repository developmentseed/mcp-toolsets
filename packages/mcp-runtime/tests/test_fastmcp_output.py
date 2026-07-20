"""The extended to_fastmcp: derived output schemas and the ToolResult gate."""

from typing import Any, NotRequired, TypedDict

import pytest
from langchain_core.tools import tool
from pydantic import BaseModel

from mcp_runtime.fastmcp_output import to_fastmcp
from mcp_runtime.tool_result import ToolError, ToolResult


class ProbeResult(ToolResult):
    items: NotRequired[list[dict[str, Any]]]


@tool
async def probe(query: str) -> ProbeResult | ToolError:
    """Return items for a query."""
    if query == "boom":
        return ToolError(error="bad_query", detail="boom")
    if query == "empty":
        return ProbeResult(message="Nothing found.")
    return ProbeResult(message=f"Found 1 for {query!r}.", items=[{"id": query}])


@tool
def message_only(text: str) -> ToolResult:
    """Echo the text (sync tool)."""
    return ToolResult(message=text)


async def run_structured(converted, arguments: dict[str, Any]) -> Any:
    """The structuredContent FastMCP would emit for a call."""
    result = await converted.run(arguments, convert_result=True)
    assert isinstance(result, tuple), "no structured content was produced"
    _unstructured, structured = result
    return structured


def test_output_schema_is_object_rooted_union():
    schema = to_fastmcp(probe).output_schema
    assert schema is not None
    assert schema["type"] == "object"
    arms = [ref["$ref"].removeprefix("#/$defs/") for ref in schema["anyOf"]]
    assert set(arms) == {"ProbeResult", "ToolError"}
    result_arm = schema["$defs"]["ProbeResult"]
    assert result_arm["properties"]["message"]["type"] == "string"
    assert "message" in result_arm["required"]
    assert schema["$defs"]["ToolError"]["required"] == ["error", "detail"]


def test_single_arm_schema_is_inlined():
    schema = to_fastmcp(message_only).output_schema
    assert schema is not None
    assert "$ref" not in schema
    assert schema["type"] == "object"
    assert "message" in schema["required"]


async def test_structured_content_is_the_returned_dict():
    converted = to_fastmcp(probe)
    structured = await run_structured(converted, {"query": "era5"})
    assert structured == {"message": "Found 1 for 'era5'.", "items": [{"id": "era5"}]}


async def test_absent_optional_keys_are_not_null_padded():
    structured = await run_structured(to_fastmcp(probe), {"query": "empty"})
    assert structured == {"message": "Nothing found."}


async def test_error_returns_conform_to_the_schema():
    structured = await run_structured(to_fastmcp(probe), {"query": "boom"})
    assert structured == {"error": "bad_query", "detail": "boom"}


async def test_sync_tool_supported():
    structured = await run_structured(to_fastmcp(message_only), {"text": "hi"})
    assert structured == {"message": "hi"}


async def test_undeclared_keys_are_dropped_from_structured_content():
    @tool
    async def sneaky(text: str) -> ToolResult:
        """Echo the text."""
        result = ToolResult(message=text)
        result["extra"] = "undeclared"  # type: ignore[typeddict-unknown-key]
        return result

    structured = await run_structured(to_fastmcp(sneaky), {"text": "hi"})
    assert structured == {"message": "hi"}


def test_basemodel_with_required_message_accepted():
    class ModelResult(BaseModel):
        message: str
        count: int = 0

    @tool
    async def modeled(text: str) -> ModelResult:
        """Echo the text."""
        return ModelResult(message=text)

    schema = to_fastmcp(modeled).output_schema
    assert schema is not None
    assert "message" in schema["required"]


@pytest.mark.parametrize(
    ("annotation", "body"),
    [
        (str, "text"),
        (dict[str, Any], {"message": "hi"}),
        (list[str], ["hi"]),
        (None, "text"),
    ],
    ids=["str", "dict-str-any", "list", "missing"],
)
def test_non_contract_annotations_rejected(annotation, body):
    async def loose(text: str):  # noqa: ANN202 - annotation applied below
        """Echo the text."""
        return body

    loose.__annotations__["return"] = annotation
    if annotation is None:
        del loose.__annotations__["return"]
    with pytest.raises(RuntimeError, match="loose"):
        to_fastmcp(tool(loose))


def test_typeddict_without_message_rejected():
    class NoMessage(TypedDict):
        data: str

    @tool
    async def messageless(text: str) -> NoMessage:
        """Echo the text."""
        return NoMessage(data=text)

    with pytest.raises(RuntimeError, match="required str 'message'"):
        to_fastmcp(messageless)


def test_non_string_message_rejected():
    class NumericMessage(TypedDict):
        message: int

    @tool
    async def numeric(text: str) -> NumericMessage:
        """Echo the text length."""
        return NumericMessage(message=len(text))

    with pytest.raises(RuntimeError, match="required str 'message'"):
        to_fastmcp(numeric)


def test_union_with_non_dict_arm_rejected():
    @tool
    async def mixed(text: str) -> ToolResult | str:
        """Echo the text."""
        return text

    with pytest.raises(RuntimeError, match="mixed"):
        to_fastmcp(mixed)
