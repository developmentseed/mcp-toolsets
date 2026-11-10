"""The chat's configuration variables, checked against the runtime that reads them.

A typo in `MCP_AGENT_UI_TITLE` fails silently and identically on both targets:
the deployment sets a variable nothing reads, the client falls back to its own
default, and the page looks merely unconfigured. Nothing else in this repo
would notice, because neither a chart render nor a stack synthesis knows what
the runtime is looking for.

Text rather than imports on purpose. `infra/cdk/config.py` needs the `infra`
dependency group and the chart is YAML, so reading both as text is what lets
one test cover both targets in the base test job.
"""

import inspect
import re
from pathlib import Path

from mcp_agent_api.ui import ENV_PREFIX, config_from_environment

ROOT = Path(__file__).resolve().parents[1]

#: Every variable the runtime reads. Not every `UiConfig` field is one: the
#: server sets `api` from where it mounted the routes, and `feedback` and
#: `view_calls` from the routes it registered.
EXPECTED = {
    f"{ENV_PREFIX}{name}"
    for name in re.findall(
        r'read\("([A-Z_]+)"', inspect.getsource(config_from_environment)
    )
}

#: Where each target says what the chat container is given. A target that has
#: been pruned away takes its files with it, so the test follows what is here —
#: and the AWS half is two files because the text and the model are set in
#: different places: `Chat` holds the page's own words, the stack passes them.
SOURCES = {
    "k8s": [ROOT / "infra/k8s/charts/mcp-chat/templates/deployment.yaml"],
    "aws": [ROOT / "infra/cdk/config.py", ROOT / "infra/cdk/toolsets_stack.py"],
}


def present(target: str) -> list[Path]:
    return [path for path in SOURCES[target] if path.is_file()]


def text_of(target: str) -> str:
    return "\n".join(path.read_text() for path in present(target))


def named_in(target: str) -> set[str]:
    return set(re.findall(rf"{ENV_PREFIX}[A-Z_]+", text_of(target)))


def test_the_runtime_reads_more_than_nothing():
    """Guards the test itself: an empty expectation would pass every case."""
    assert EXPECTED >= {f"{ENV_PREFIX}TITLE", f"{ENV_PREFIX}EXAMPLES"}


def test_a_target_is_here_to_check():
    """Both files pruned away would make the two tests below vacuous."""
    assert any(present(target) for target in SOURCES)


def test_each_target_sets_exactly_what_the_client_reads():
    for target in SOURCES:
        if not present(target):
            continue  # pruned away with its target
        named = named_in(target)
        assert named == EXPECTED, (
            f"{target}: sets {sorted(named - EXPECTED)} that nothing reads, "
            f"and misses {sorted(EXPECTED - named)}"
        )


def test_the_provider_variables_are_the_ones_the_agent_reads():
    """These two are the runtime's own settings names, not this repo's, and a
    deployment that misspells either starts a process that cannot build an
    agent — which is a crash loop, not a quiet default."""
    for target in SOURCES:
        if not present(target):
            continue
        text = text_of(target)
        assert "PROVIDER_MODEL" in text, target
        assert "PROVIDER_API_KEY" in text, target
