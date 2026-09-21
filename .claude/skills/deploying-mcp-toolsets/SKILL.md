---
name: deploying-mcp-toolsets
description: Work in this repo, which deploys toolsets as MCP services. Covers adding and removing a toolset, what a change redeploys, the target markers, and the checks to run. Use when adding, removing or changing a toolset here, editing infra/ or the workflows, or working out why a deploy did or did not happen.
---

# Working in this repo

This repo turns directories under `toolsets/` into deployed MCP services. It
owns `toolsets/`, `infra/`, the `Dockerfile`s, the workflows and
`tests/test_contract.py`.

**Writing the tools themselves is not covered here.** The runtime ships its
own skill for that, matching the version this repo pins; `uv run mcp-toolset
skill` prints its path. It also carries the rule that this repo owns no
runtime code.

`README.md` is the reference for everything below. This file is the procedure.

## Get these right first

**1. Know what your change redeploys.** This is the difference between
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

**2. Deleting a toolset directory tears down the live service.** The deploy
reconciles what is running against `toolsets/`, so a merged deletion is a
teardown. Use `./scripts/remove-toolset <name>` rather than `rm -rf`.

## Adding a toolset

`uv run mcp-toolset new my-toolset` scaffolds it; the runtime's skill covers
that part. Two things only this repo knows:

- The deployment config it writes comes from the templates under `infra/`,
  named by `[tool.mcp-toolset] deployment-config` in the root
  `pyproject.toml`. Change the template, not the copy in each toolset.
- The deploy relies on the names: directory `toolsets/<name>` in kebab-case,
  module `<name_snake_case>.tools`, service and image `mcp-<name>`.

## Checks before you open a PR

```bash
./scripts/lint      # ruff + mypy; ./scripts/format to autofix
./scripts/test      # every package, plus the contract sweep over toolsets/
```

`tests/test_contract.py` sweeps every toolset against the runtime's gates.
`tests/` holds only what is about *this repo's* toolsets; tests for runtime
behaviour belong upstream.

Then serve it and make a real call, as the runtime's skill describes. A
toolset with a view needs `./scripts/build-views` first. Built bundles live
at `<package>/views/*.html`, are git-ignored, and `mcp-serve` aborts without
them.

## Conventions CI enforces and nothing else states

- Dependency ranges are bounded `<next-major,>=current`. Check PyPI for the
  current version when adding one.
- Test filenames are unique across the whole workspace. mypy and pytest sweep
  every package in one run, so two `test_tools.py` collide.

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
