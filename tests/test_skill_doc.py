"""The repo's own skill: an agent has to be able to load it and act on it."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude" / "skills" / "deploying-mcp-toolsets" / "SKILL.md"


def test_the_frontmatter_carries_a_description() -> None:
    """`description` is what an agent matches on, so an empty one is inert."""
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "the skill needs a frontmatter block"
    frontmatter = text.split("---\n")[1]
    assert re.search(r"^description: \S", frontmatter, re.MULTILINE)


def test_every_script_it_names_is_here() -> None:
    """It tells an agent what to run. A stale command is worse than none."""
    named = set(
        re.findall(r"(scripts/[a-z][a-z-]*)", SKILL.read_text(encoding="utf-8"))
    )
    assert named, "the skill names no scripts, so this test checks nothing"
    for script in sorted(named):
        assert (ROOT / script).exists(), f"{script} does not exist"
