# CLAUDE.md

Architecture, deployment and usage are documented in README.md — read it
first. This file holds only what an agent cannot derive from it.

## This repo owns no runtime code

`mcp_runtime`, `mcp_cli`, `mcp_agent` and `mcp_toolset` come from the
`mcp-toolsets-runtime` PyPI package, pinned in the root `pyproject.toml`. Never
add a module under those names here, and never patch runtime behaviour locally —
fix it in
[mcp-toolsets-runtime](https://github.com/developmentseed/mcp-toolsets-runtime),
release, then bump the pin. What this repo owns is `toolsets/`, `infra/` (the
deployment target — see README), the `Dockerfile`, the workflows and
`tests/test_contract.py`.

## Commands

- `uv sync` once, then `./scripts/lint`, `./scripts/test`, `./scripts/format`.
- New toolset: `uv run mcp-toolset new <name>` (from the runtime) — never
  hand-roll the layout. Add `--with-ui` for a toolset with a React view (see
  README "Toolset UI views"). The deployment config files it writes come from
  `[tool.mcp-toolset] deployment-config` in the root `pyproject.toml`, which
  points at the templates under `infra/` — edit those, not the copies in each
  toolset, when the shape changes.
- Remove a toolset: `./scripts/remove-toolset <name>`.
<!-- target:aws -->
- The AWS target lives in `infra/cdk` (CDK, Python). It needs node — `aws-cdk-lib`
  is a Python package with a JavaScript engine underneath — and its deps are a
  dependency group: `uv sync --group infra`. Synthesise with
  `uv run --group infra python -m infra.cdk.app -c instance=dev -c imagePrefix=... -c imageTags='{...}'`.
<!-- /target:aws -->
- Build toolset UIs: `./scripts/build-views` (needs node). Built view bundles
  live at `<package>/views/*.html`, are git-ignored, and must exist before
  `mcp-serve` or `build_server` aborts — the Dockerfile's node stage, the CI
  `ui` job, and this script rebuild them.
- The hosted chat is the runtime's `mcp_agent_api`, page included: the web
  client ships inside the wheel, so nothing here builds or vendors a frontend
  and `Dockerfile.chat` runs `uvicorn`. Its text is `MCP_AGENT_UI_*`, set
  <!-- target:k8s -->
  in `infra/k8s/charts/mcp-chat/values.yaml`.
  <!-- /target:k8s -->
  <!-- target:aws -->
  in `Chat`'s defaults in `infra/cdk/config.py`.
  <!-- /target:aws -->

## Safety

- Never read `.env` — it contains real API keys.
<!-- target:k8s -->
- Never run `kubectl` or `helm` against a locally configured context: the
  deployment cluster is reached only via CI (or a kubeconfig the user
  manages outside this repo). Give the user commands to run themselves.
<!-- /target:k8s -->

<!-- target:aws -->
## The AWS target's one hard rule

Synthesis must never look anything up from an account: subnets arrive as
identifiers with their availability zones, a hosted zone as its name *and* id,
and the stacks are environment-agnostic (naming an account or region makes CDK
resolve that region's availability zones, which is a credentialled call). CI
fails if `cdk.out/*/manifest.json` has a non-empty `missing`. That rule is what
lets a PR check the stack with no account attached — don't trade it away for a
convenience constructor.
<!-- /target:aws -->

## Conventions CI enforces but nothing else documents

- Dependency ranges are bounded `<next-major,>=current` — check PyPI for
  the current version when adding one.
- Test filenames must be unique across the whole workspace: mypy and
  pytest sweep every package here in one run.
- Tools that do I/O are `async def`; sync tools are for pure computation
  only (the runtime executes them in a thread pool).
- `tests/` holds only what is about *this repo's* toolsets — `test_contract.py`
  sweeps `toolsets/` against the runtime's gates. Tests for runtime behaviour
  belong upstream, not here.

## Deployment semantics that bite

- Changes under `.github/` trigger no builds or deploys — after fixing a
  workflow, run it via workflow_dispatch.
- Shared paths (`infra/`, `Dockerfile`, `uv.lock`, root `pyproject.toml`) rebuild and redeploy ALL toolsets; only `toolsets/<name>/` changes are scoped
  to one service. A runtime version bump lands in `uv.lock`, so it redeploys
  everything — which is what you want.
- Merging a toolset directory deletion tears down the live service — the
  deploy reconciles what is running against `toolsets/`.
<!-- target:both -->
- Both deployment targets live here, and an instance keeps one:
  `./scripts/bootstrap` prunes the other. A `target:<name>` marker comment
  delimits a block that goes with its target, so never split one across a file
  and never leave one unclosed — `scripts/prune-target` reads them, and a test
  checks they are balanced. Both that script and its test are removed by the
  prune, along with everything else that is only about the choice.
<!-- /target:both -->
