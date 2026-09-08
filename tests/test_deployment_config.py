"""The deployment config templates, and the declaration that points at them.

`mcp-toolset new` copies these into every new toolset, so a key that stops
being real here is a key someone sets in good faith and watches do nothing.
Both targets are checked against their own authority: the chart's values for
Helm, the stack's own config for AWS.

Stdlib only, deliberately. This runs in the base test job, which has neither
the `infra` dependency group nor node, so nothing here may import the stack.
"""

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART_VALUES = ROOT / "infra/k8s/charts/mcp-toolset/values.yaml"
STACK_CONFIG = ROOT / "infra/cdk/config.py"

#: A commented-out example key at the top level of a template: `# secrets:`.
#: Deliberately permissive about the name — a pattern that only matched keys
#: that happen to be valid would drop a wrong one out of the set instead of
#: failing on it, which is the one thing this file exists to catch.
EXAMPLE_KEY = re.compile(r"^# (?P<key>[A-Za-z][A-Za-z_]*):", re.MULTILINE)


def declared() -> list[dict[str, str]]:
    """What the root pyproject says a new toolset's config files are."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return pyproject["tool"]["mcp-toolset"]["deployment-config"]


def example_keys(template: Path) -> set[str]:
    return {match["key"] for match in EXAMPLE_KEY.finditer(template.read_text())}


def test_every_declared_template_exists():
    """A moved template is a toolset scaffolded without the file its deployment
    reads — and the scaffolder only finds out at the next `mcp-toolset new`."""
    for entry in declared():
        assert (ROOT / entry["template"]).is_file(), entry["template"]


def test_the_declared_targets_are_ones_this_repo_has():
    """The template carries both; `scripts/prune-target` drops one at bootstrap,
    so a declaration that is a subset is a bootstrapped instance, not a bug."""
    paths = {entry["path"] for entry in declared()}
    assert paths and paths <= {"toolset.yaml", "toolset.aws.yaml"}


def test_the_helm_examples_are_keys_the_chart_accepts():
    template = ROOT / "infra/k8s/toolset.template.yaml"
    if not template.is_file():
        return  # an instance that kept AWS

    top_level = {
        match["key"]
        for match in re.finditer(
            r"^(?P<key>[a-z][a-zA-Z]*):", CHART_VALUES.read_text(), re.MULTILINE
        )
    }
    assert example_keys(template) <= top_level, example_keys(template) - top_level


def test_the_aws_examples_are_fields_the_stack_reads():
    """Parsed from the source rather than imported: the stack needs node, and
    this test runs where there is none."""
    template = ROOT / "infra/cdk/toolset.template.yaml"
    if not template.is_file():
        return  # an instance that kept Kubernetes
    tree = ast.parse(STACK_CONFIG.read_text())
    toolset = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "Toolset"
    )
    fields = {
        node.target.id
        for node in toolset.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    # `size` is the file's name for the cpu/memory pair the stack holds as two
    # fields, so it is the one key that is a shape rather than a field.
    keys = example_keys(template) - {"size"}
    assert keys <= fields, keys - fields
    assert {"cpu", "memory"} <= fields


def test_each_toolset_carries_both_files():
    """What a new toolset gets and what the shipped ones have are the same
    file, so an example that rots is visible in the diff of the template."""
    for toolset in (ROOT / "toolsets").iterdir():
        if not (toolset / "pyproject.toml").is_file():
            continue
        for entry in declared():
            assert (toolset / entry["path"]).is_file(), (
                f"{toolset.name}/{entry['path']}"
            )
