"""The repo's own skill: an agent has to be able to load it and act on it."""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude" / "skills" / "deploying-mcp-toolsets" / "SKILL.md"


def frontmatter() -> dict[str, str]:
    """The block an agent reads to decide whether the skill is relevant."""
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "the skill needs a frontmatter block"
    fields = {}
    for line in text.split("---\n")[1].splitlines():
        key, separator, value = line.partition(":")
        assert separator, f"frontmatter line is not key: value -- {line!r}"
        fields[key.strip()] = value.strip()
    return fields


@pytest.mark.parametrize("field", ["name", "description"])
def test_the_frontmatter_carries(field: str) -> None:
    """`description` is what an agent matches on, so an empty one is inert."""
    assert frontmatter().get(field)


def test_the_name_matches_the_directory() -> None:
    assert frontmatter()["name"] == SKILL.parent.name


def test_every_script_it_names_is_here() -> None:
    """It tells an agent what to run. A stale command is worse than none."""
    named = set(
        re.findall(r"(scripts/[a-z][a-z-]*)", SKILL.read_text(encoding="utf-8"))
    )
    assert named, "the skill names no scripts, so this test checks nothing"
    for script in sorted(named):
        assert (ROOT / script).exists(), f"{script} does not exist"


def test_it_points_at_the_deployment_config_this_repo_declares() -> None:
    """The scaffold claim only holds while the root pyproject declares it."""
    assert "[tool.mcp-toolset] deployment-config" in SKILL.read_text(encoding="utf-8")
    root = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert root["tool"]["mcp-toolset"]["deployment-config"]
