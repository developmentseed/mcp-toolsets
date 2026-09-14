---
name: deploying-mcp-toolsets
description: Work in this repo, which deploys toolsets as MCP services. Covers adding and removing a toolset, what a change redeploys, the target markers, and the checks to run. Use when adding, removing or changing a toolset here, editing infra/ or the workflows, or working out why a deploy did or did not happen.
---

# Working in this repo

This repo turns directories under `toolsets/` into deployed MCP services. It
owns `toolsets/`, `infra/`, the `Dockerfile`s, the workflows and
`tests/test_contract.py`.

**Writing the tools themselves is not covered here.** That belongs to
`mcp-toolsets-runtime`, which ships its own skill matching the version this
repo pins:

```bash
uv run mcp-toolset skill --install   # writes .claude/skills/writing-mcp-toolsets/
```

If that command does not exist, the pinned runtime predates it. Read
`docs/CONSUMING.md` in
[mcp-toolsets-runtime](https://github.com/developmentseed/mcp-toolsets-runtime)
instead.

`README.md` is the reference for everything below. This file is the procedure.

## Get these right first

**1. This repo owns no runtime code.** `mcp_runtime`, `mcp_state`, `mcp_cli`,
`mcp_agent`, `mcp_agent_api` and `mcp_toolset` come from the
`mcp-toolsets-runtime` package, pinned in the root `pyproject.toml`. Never add
a module under one of those names, and never patch runtime behaviour here.
Nothing local survives the next `uv sync`. Fix it upstream, release, bump the
pin.

**2. Know what your change redeploys.** This is the difference between
touching one service and touching all of them.

| What you change | What redeploys |
| --- | --- |
| `toolsets/<name>/` | that one service |
| `infra/`, a `Dockerfile`, `uv.lock`, the root `pyproject.toml` | every toolset |
| anything under `.github/` | nothing; no build, no deploy |

A runtime bump lands in `uv.lock`, so it redeploys everything. That is correct,
not a mistake to route around.

After fixing a workflow, run it with `workflow_dispatch`. Merging it does
nothing on its own.

**3. Deleting a toolset directory tears down the live service.** The deploy
reconciles what is running against `toolsets/`, so a merged deletion is a
teardown. Use `./scripts/remove-toolset <name>` rather than `rm -rf`.

## Adding a toolset

```bash
uv run mcp-toolset new my-toolset     # --with-ui for a React view
```

Never hand-roll the directory. The generator writes the package, the test, the
pyproject and the deployment config this repo declares under
`[tool.mcp-toolset] deployment-config` in the root `pyproject.toml`. Those
files come from the templates under `infra/`. If the shape needs to change,
edit the template, not the copy in each toolset.

Then write the tools, following the runtime's skill.

The conventions the deploy relies on: directory `toolsets/<name>` in
kebab-case, module `<name_snake_case>.tools`, service and image `mcp-<name>`.

## Checks before you open a PR

```bash
./scripts/lint      # ruff + mypy; ./scripts/format to autofix
./scripts/test      # every package, plus the contract sweep over toolsets/
```

The contract sweep is `tests/test_contract.py`. It imports every toolset and
checks the `TOOLS` export, non-empty docstrings, the typed return contract, and
that no sync tool does blocking I/O. `tests/` holds only what is about *this
repo's* toolsets; tests for runtime behaviour belong upstream.

Then serve it and make a real call, because the tests do not exercise the
schema the model actually sees:

```bash
uv run mcp-serve-local
uv run mcp-cli list --url http://localhost:8000/my-toolset/mcp
uv run mcp-cli call my_tool arg=value --url http://localhost:8000/my-toolset/mcp
```

A toolset with a view needs `./scripts/build-views` first. Built bundles live
at `<package>/views/*.html`, are git-ignored, and `mcp-serve` aborts without
them.

## Conventions CI enforces and nothing else states

- Dependency ranges are bounded `<next-major,>=current`. Check PyPI for the
  current version when adding one.
- Test filenames are unique across the whole workspace. mypy and pytest sweep
  every package in one run, so two `test_tools.py` collide.
- Tools that do I/O are `async def`. Sync is for pure computation only.

<!-- target:both -->
## Two deployment targets

Both Kubernetes and AWS ship here, and an instance keeps one.
`./scripts/bootstrap` prunes the other.

A `target:<name>` marker comment opens a block that goes with that target and
`/target:<name>` closes it, inside whatever comment syntax the file takes: `#`
in Python and shell, an HTML comment in markdown and YAML. A third name covers
text that exists only while the choice does.

Never write a marker you do not mean, including in prose about markers: the
prune matches the string anywhere in a line. Never split a pair across a file
and never leave one unclosed. `scripts/prune-target` reads them, a test checks
they balance, and both that script and its test go with the prune.

**`scripts/prune-target` takes its root from where the script lives, not from
your working directory.** Running a copy's script prunes that copy; running
this repo's script prunes this repo, from anywhere. There is no dry run, and
the files it edits include untracked ones, which `git checkout` will not bring
back.
<!-- /target:both -->

<!-- target:aws -->
## The AWS target's one hard rule

**Synthesis must never look anything up from an account.** Subnets arrive as
identifiers with their availability zones, a hosted zone as its name *and* id,
and the stacks name no account or region, because naming a region makes CDK
resolve that region's availability zones, which is a credentialled call. CI
fails if `cdk.out/*/manifest.json` has a non-empty `missing`. That rule is what
lets a PR check the stack with no account attached. Do not trade it for a
convenience constructor.

Synthesising by hand needs a tag for every component, `index-aws` and `chat`
included, not just the toolset you are working on. See "Working on the stack"
in `README.md`.
<!-- /target:aws -->

## Never do these

- **Never read `.env`.** It holds real API keys.
<!-- target:k8s -->
- **Never run `kubectl` or `helm` against a locally configured context.** The
  deployment cluster is reached through CI, or a kubeconfig the user manages
  outside this repo. Give the user the command to run instead.
<!-- /target:k8s -->
- **Never put a credential in a file you commit,** including in a comment
  saying what it was.
