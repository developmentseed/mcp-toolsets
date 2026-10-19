"""LangChain tools demonstrating a tool that asks the user a question.

Example of a toolset tool that cannot finish without the user: it raises
``AskUser`` with what it needs, the agent puts the question to the user, and
then calls the tool again with the answer in ``answers()``. The "download" is
stubbed; a real implementation would fetch the year the user chose.
"""

from langchain_core.tools import tool

from mcp_runtime.questions import AskUser, answers
from mcp_runtime.tool_result import ToolResult

YEAR = {
    "type": "object",
    "properties": {"year": {"type": "integer", "minimum": 1940, "maximum": 2026}},
    "required": ["year"],
}


@tool
async def download(dataset: str) -> ToolResult:
    """Download one year of a dataset, asking the user which year."""
    # Ask first: the tool runs from the start on both calls, so work done
    # before asking is done twice.
    if (replies := answers()) is None:
        raise AskUser(year=(f"Which year of {dataset}?", YEAR))
    chosen = replies["year"].content  # None when the user declined
    if chosen is None:
        return ToolResult(
            message=f"No year chosen, so nothing downloaded from {dataset}."
        )
    return ToolResult(message=f"Downloaded {dataset} for {chosen['year']}.")


TOOLS = [download]
