# CLAUDE.md

Architecture, deployment and usage are documented in README.md — read it
first. This file holds only what an agent cannot derive from it.

## Commands

- `uv sync` once, then `./scripts/lint`, `./scripts/test`, `./scripts/format`.
- New toolset: `./scripts/new-toolset <name>` — never hand-roll the layout.
- Remove a toolset: `./scripts/remove-toolset <name>`.

## Safety

- Never read `.env` — it contains real API keys.
- Never run `kubectl` or `helm` against a locally configured context: the
  deployment cluster is reached only via CI (or a kubeconfig the user
  manages outside this repo). Give the user commands to run themselves.

## Conventions CI enforces but nothing else documents

- Dependency ranges are bounded `<next-major,>=current` — check PyPI for
  the current version when adding one.
- Test filenames must be unique across the whole workspace: mypy and
  pytest run once over `packages/` and `toolsets/` together.
- Tools that do I/O are `async def`; sync tools are for pure computation
  only (the runtime executes them in a thread pool).
- Tests under `packages/` must not import real toolsets — toolsets come and
  go (and removal uninstalls the live service). Use synthetic modules as
  fixtures, as in `packages/mcp-runtime/tests/test_server.py`.

## Deployment semantics that bite

- Changes under `.github/` trigger no builds or deploys — after fixing a
  workflow, run it via workflow_dispatch.
- Shared paths (`packages/`, `charts/`, `Dockerfile`, `uv.lock`, root
  `pyproject.toml`) rebuild and redeploy ALL toolsets; only
  `toolsets/<name>/` changes are scoped to one service.
- Merging a toolset directory deletion uninstalls the live service — the
  deploy workflow reconciles releases against `toolsets/`.
