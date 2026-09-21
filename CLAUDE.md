# CLAUDE.md

Architecture, deployment and usage are documented in README.md — read it
first. This file holds only what an agent cannot derive from it.

## Two skills carry the procedure

- **Working in this repo** — adding and removing a toolset, what a change
  redeploys, the target markers, the checks:
  `.claude/skills/deploying-mcp-toolsets/SKILL.md`.
- **Writing the tools** — the plugin contract, typed returns, session state,
  credentials, views: the runtime's own skill, whose path
  `uv run mcp-toolset skill` prints. It ships in the wheel, so it always
  matches the pinned version. Do not install a copy here: this repo owns no
  runtime content, and a copy goes stale at the next bump.

Read the relevant one before changing anything. What follows is what must be
true even if neither is loaded.

## This repo owns no runtime code

`mcp_runtime`, `mcp_cli`, `mcp_agent` and `mcp_toolset` come from the
`mcp-toolsets-runtime` PyPI package, pinned in the root `pyproject.toml`. Never
add a module under those names here, and never patch runtime behaviour locally —
fix it in
[mcp-toolsets-runtime](https://github.com/developmentseed/mcp-toolsets-runtime),
release, then bump the pin. What this repo owns is `toolsets/`, `infra/` (the
deployment target — see README), the `Dockerfile`, the workflows and
`tests/test_contract.py`.

## Safety

- Never read `.env` — it contains real API keys.
- Merging a toolset directory deletion tears down the live service: the deploy
  reconciles what is running against `toolsets/`. Use
  `./scripts/remove-toolset <name>`, never `rm -rf`.
<!-- target:both -->
- `scripts/prune-target` takes its root from where the script lives, not from
  the working directory, and edits untracked files with no dry run. Running
  this repo's copy prunes this repo, from anywhere.
<!-- /target:both -->
<!-- target:k8s -->
- Never run `kubectl` or `helm` against a locally configured context: the
  deployment cluster is reached only via CI (or a kubeconfig the user
  manages outside this repo). Give the user commands to run themselves.
<!-- /target:k8s -->

## Commands

`uv sync` once, then `./scripts/lint`, `./scripts/test`, `./scripts/format`.
The skill above covers the rest.
