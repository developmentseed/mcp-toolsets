"""The bootstrap-time prune that leaves an instance with one deployment target.

Two kinds of check. The first exercise `strip_blocks` on text written here, so
a failure points at the stripper. The rest prune a copy of this repository and
read the result, because what actually breaks is not the algorithm — it is a
marker someone forgets to close, or a path that moves, and neither shows up
until an instance is bootstrapped and finds half a target still in the tree.

Stdlib only: this runs in the base test job, which has neither the `infra`
dependency group nor node.
"""

import importlib.machinery
import importlib.util
import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_pruner():
    """Import `scripts/prune-target`, which has no `.py` to import by name."""
    spec = importlib.util.spec_from_loader(
        "prune_target",
        importlib.machinery.SourceFileLoader(
            "prune_target", str(ROOT / "scripts/prune-target")
        ),
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


prune_target = load_pruner()


def test_a_block_goes_with_its_markers():
    text = "keep\n# target:aws\ndrop\n# /target:aws\nkeep too\n"
    assert prune_target.strip_blocks(text, "aws") == "keep\nkeep too\n"


def test_the_other_target_is_left_alone():
    text = "# target:k8s\nmine\n# /target:k8s\n# target:aws\ntheirs\n# /target:aws\n"
    assert (
        prune_target.strip_blocks(text, "aws") == "# target:k8s\nmine\n# /target:k8s\n"
    )


def test_html_comments_are_the_same_markers():
    text = "a\n<!-- target:aws -->\nb\n<!-- /target:aws -->\nc\n"
    assert prune_target.strip_blocks(text, "aws") == "a\nc\n"


def test_a_both_block_goes_whichever_target_went():
    """`target:both` is for text about the choice, so it never survives one."""
    text = "a\n<!-- target:both -->\npick one\n<!-- /target:both -->\nb\n"
    for target in prune_target.TARGETS:
        assert "pick one" not in prune_target.strip_blocks(
            prune_target.strip_blocks(text, target), prune_target.BOTH
        )


def test_it_refuses_to_take_the_last_target(tmp_path):
    root = pruned_copy(tmp_path, "aws")
    try:
        prune_target.prune(root, "k8s")
    except SystemExit as refusal:
        assert "only target left" in str(refusal)
    else:
        raise AssertionError("pruned the last target")
    assert (root / "infra/k8s").is_dir()


def test_every_path_it_deletes_is_here_to_delete():
    """A moved directory would make the prune a silent partial success."""
    for target, paths in prune_target.PATHS.items():
        for relative in paths:
            assert (ROOT / relative).exists(), f"{target}: {relative}"
    for relative in prune_target.SELF:
        assert (ROOT / relative).exists(), relative


def test_the_toolset_config_names_match_what_the_scaffolder_writes():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    declared = {
        entry["path"] for entry in pyproject["tool"]["mcp-toolset"]["deployment-config"]
    }
    assert set(prune_target.TOOLSET_CONFIG.values()) == declared


#: The two files that talk about markers for a living, and so contain the
#: literal text of one without being one.
MARKER_LITERATURE = {"scripts/prune-target", "tests/test_prune_target.py"}


def test_markers_are_balanced_everywhere():
    """An unclosed marker eats the rest of the file, and only at bootstrap."""
    names = [*prune_target.TARGETS, prune_target.BOTH]
    for path in prune_target.text_files(ROOT):
        if str(path.relative_to(ROOT)) in MARKER_LITERATURE:
            continue
        text = path.read_text()
        for name in names:
            opening, closing = prune_target.marked(name)
            # The closing marker contains the opening one, so count lines.
            closes = sum(1 for line in text.splitlines() if closing in line)
            opens = sum(1 for line in text.splitlines() if opening in line) - closes
            assert opens == closes, f"{path.relative_to(ROOT)}: {name}"


def pruned_copy(tmp_path: Path, target: str) -> Path:
    """A copy of what this repo *ships*, with one target pruned.

    Tracked files only: an untracked `.env` or kubeconfig in a working
    checkout is not part of the template, and copying one into a temp
    directory to test a text substitution would be a poor trade.
    """
    root = tmp_path / f"without-{target}"
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True,
        check=True,
    ).stdout
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        source = ROOT / entry.decode()
        if not source.is_file():
            continue
        destination = root / entry.decode()
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    prune_target.prune(root, target)
    return root


def test_pruning_aws_leaves_a_kubernetes_repo(tmp_path):
    root = pruned_copy(tmp_path, "aws")

    assert not (root / "infra/cdk").exists()
    assert not (root / ".github/workflows/deploy-aws.yml").exists()
    assert not (root / "cdk.json").exists()
    assert (root / "infra/k8s/charts").is_dir()
    assert (root / ".github/workflows/deploy.yml").is_file()

    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    groups = pyproject["dependency-groups"]
    assert "index" in groups and "chat" in groups
    assert "index-aws" not in groups and "infra" not in groups
    assert [
        e["path"] for e in pyproject["tool"]["mcp-toolset"]["deployment-config"]
    ] == ["toolset.yaml"]

    ci = (root / ".github/workflows/ci.yml").read_text()
    assert "\n  helm:\n" in ci and "\n  synth:\n" not in ci
    assert "- index\n" in ci and "- index-aws\n" not in ci


def test_pruning_kubernetes_leaves_an_aws_repo(tmp_path):
    root = pruned_copy(tmp_path, "k8s")

    assert not (root / "infra/k8s").exists()
    assert not (root / ".github/workflows/deploy.yml").exists()
    assert (root / "infra/cdk/toolsets_stack.py").is_file()
    assert (root / ".github/workflows/deploy-aws.yml").is_file()

    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    groups = pyproject["dependency-groups"]
    assert "index-aws" in groups and "infra" in groups and "chat" in groups
    assert "index" not in groups
    assert [
        e["path"] for e in pyproject["tool"]["mcp-toolset"]["deployment-config"]
    ] == ["toolset.aws.yaml"]

    ci = (root / ".github/workflows/ci.yml").read_text()
    assert "\n  synth:\n" in ci and "\n  helm:\n" not in ci

    # A repo that has chosen cannot choose again, so the machinery goes too.
    assert not (root / "scripts/prune-target").exists()
    assert not (root / "tests/test_prune_target.py").exists()

    # The Kubernetes namespace placeholder is only ever substituted for that
    # target, so a leftover would sit in the docs of an AWS repo unresolved.
    assert "__MCP_NAMESPACE__" not in (root / "README.md").read_text()


def test_a_pruned_repo_keeps_no_markers(tmp_path):
    """Whatever survives must read as prose, not as a half-stripped template.

    The dropped target's blocks go; the kept target's markers are unwrapped,
    so nothing in the result advertises that a choice was ever made here.
    """
    names = [*prune_target.TARGETS, prune_target.BOTH]
    for target in prune_target.TARGETS:
        root = pruned_copy(tmp_path, target)
        for path in prune_target.text_files(root):
            relative = path.relative_to(root)
            if str(relative) in MARKER_LITERATURE:
                continue
            text = path.read_text()
            for name in names:
                assert f"target:{name}" not in text, f"{relative}: {name}"


def test_each_toolset_loses_only_the_other_target(tmp_path):
    root = pruned_copy(tmp_path, "aws")
    for toolset in (root / "toolsets").iterdir():
        if not (toolset / "pyproject.toml").is_file():
            continue
        assert (toolset / "toolset.yaml").is_file(), toolset.name
        assert not (toolset / "toolset.aws.yaml").exists(), toolset.name
