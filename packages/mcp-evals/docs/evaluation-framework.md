# Evaluation framework — reference

Reference for `mcp-evals`, the harness that evaluates the mcp-toolsets agent.
For day-to-day usage and option flags, see the [package README](../README.md);
this document covers the design, the data model, scoring, and how to extend it.

## What it evaluates, and why this shape

The repo ships toolsets (LangChain tools served over MCP) and an `mcp-agent`
that drives them with a Mistral model. Per-tool unit tests
(`toolsets/*/tests/`) check tools in isolation, but nothing measured the thing
users actually experience: **given a question, does the agent pick the right
tools and produce a good answer?** `mcp-evals` fills that gap.

It is deliberately **end-to-end and agent-centric** (not per-tool): a case is a
user query, and we score the agent's behaviour on it. The framework was shaped
by four decisions:

| Decision | Choice | Why |
|---|---|---|
| Scope | Agents only (v1) | Tools already have unit tests; the unknown is agent behaviour. |
| How to run the agent | **In-process**, reusing `mcp-agent` | There is no agent API. Calling the real `build_agent`/`run_turn` exercises the exact user code path with no parallel implementation to drift. |
| Answer judge | **Mistral** | Reuses the key/stack already in the repo; one fewer provider/secret. |
| Eval data | **Public Google Sheet** (CSV export) | Non-engineers can collaborate on cases; zero auth keeps the reader trivial. |
| When it runs in CI | **Manual** (`workflow_dispatch`) | LLM runs are slow, nondeterministic, and billed — unsuitable for gating PRs. |

The approach is inspired by [`wri/gnw-evals`](https://github.com/wri/gnw-evals)
— the sheet-as-CSV loader, the present-only score averaging, and the
hard-logic + LLM-judge split are borrowed from it — but adapted: gnw-evals
calls a live agent API and judges with Anthropic; we run the agent in-process
and judge with Mistral.

## Architecture

```
packages/mcp-evals/src/mcp_evals/
  config.py    EvalSettings (MISTRAL_API_KEY, model, sheet id, thresholds)
  dataset.py   EvalCase schema + sheet/CSV loading + filtering
  runner.py    run the agent per case, capture answer + tool trajectory
  scoring.py   deterministic checks + Mistral judge -> Scores
  report.py    summary/detailed CSVs + rich console pass-rate table
  cli.py       `mcp-evals run` wiring it together
  examples/gold.csv   sample case set (same shape as a sheet tab)
```

### Data flow

```
sheet CSV / --file ──▶ parse_cases ──▶ select(group, sample)
                                            │
                                            ▼
                         run_cases  (build_agent once, then
                          per case: user_credentials + run_turn)
                                            │
                            CaseRun{answer, tool_calls, error}
                                            │
                                            ▼
                         score_run ──▶ Scores{tool, dataset, answer}
                                            │
                                            ▼
                    report: console table + summary.csv + detailed.csv
```

### Reuse, not reimplementation

The runner imports the agent wholesale from `mcp_agent.main`:

- `build_agent(url, model, api_key)` — discovers the tools behind an MCP URL and
  builds the tool-calling agent **once** per run.
- `run_turn(agent, [], query)` — runs one case as a single-turn conversation and
  returns the full message history.
- `user_credentials(headers)` — wraps each run so credential-needing toolsets
  (e.g. CDS via `x-cds-token`) receive secrets over the MCP transport without the
  model ever seeing them.

The tool trajectory is pulled from the history with the same
`message.tool_calls` access the agent's own chat loop uses, so the eval sees
exactly what the agent did.

## Eval data model

Cases live in **one tab** of a Google Sheet, shared "anyone with the link can
view", read via its CSV export URL:

```
https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}
```

No Google credentials are involved. A local CSV with the same columns
(`--file`) is handled by the same loader, which is what the tests and the
bundled `examples/gold.csv` use.

### Columns

| column | required | meaning |
|---|---|---|
| `test_id` | ✓ | stable id, e.g. `cds-search-001`; tracks a case across runs |
| `group` | | category (often the toolset); filter with `--group`, grouped in the report |
| `query` | ✓ | the user message (single turn) |
| `expected_answer` | | acceptance criteria in plain language; graded **semantically** |
| `expected_dataset_ids` | | **comma**-separated ids, any one acceptable (any-of) |
| `expected_tools` | | **semicolon**-separated tool names that must be called |
| `forbidden_tools` | | **semicolon**-separated tool names that must not be called |
| `status` | | blank = active; `skip` = excluded |
| `notes` | | free text for collaborators; ignored by code |

Modelled as `EvalCase` (Pydantic, `extra="allow"`). Design points:

- **Fill in only what you care about.** An empty expected column is excluded
  from that case's score (present-only averaging), so a row can test just tools,
  just the answer, or any combination.
- **Two separators on purpose.** `expected_dataset_ids` splits on **comma**
  (dataset ids never contain commas, and "any of these is acceptable" reads
  naturally as a comma list); tool lists split on **semicolon**.
- **Unknown columns survive.** Extra columns (priority, author, ticket link) are
  preserved on the model and ignored by scoring, so the sheet can grow without
  code changes. Future scoring dimensions become new optional columns.
- A case with no expectation at all is flagged (it would score nothing).

## Scoring

Every dimension is `1`, `0`, or `None` (no expectation set). Defined in
`scoring.py`:

- **`tool_score`** — `1` iff every `expected_tools` was called and no
  `forbidden_tools` was. `None` if neither column is set.
- **`dataset_score`** — `1` iff **any** `expected_dataset_ids` appears
  (case-insensitive) in either a tool call's serialised arguments or the final
  answer text. `None` if the column is empty. The matched ids are recorded for
  the detailed report.
- **`answer_score`** — a Mistral judge (`ChatMistralAI` +
  `with_structured_output(JudgeResult)`, `temperature=0`) grades the answer
  against `expected_answer` for *semantic* equivalence, returning `{score, reason}`.
  `None` if `expected_answer` is empty, or if the run errored (no answer to judge).

**Roll-up:** `overall` is the mean of the present (non-`None`) scores, rounded to
two places; a case **passes** at `overall >= 0.7` (`PASS_THRESHOLD` in
`config.py`). A run that raised an exception keeps every dimension `None`, so it
reports as an error rather than a misleading zero.

### Outputs

`report.py` writes two timestamped CSVs to `--out` (default `outputs/`):

- **`<ts>_summary.csv`** — one row per case: id, group, query, overall, passed,
  the three sub-scores, duration, error. For at-a-glance pass rates.
- **`<ts>_detailed.csv`** — adds expected-vs-actual for every dimension
  (expected/called/forbidden tools, expected/matched dataset ids, expected
  answer, actual answer, judge reason). For debugging failures.

The console shows a per-case table plus overall and per-group pass rates.

## CLI

```sh
mcp-evals run --url <mcp-url> [--file CSV | --sheet-id ID --gid N]
              [--group G] [--sample N] [--workers N]
              [--credential "Header: value"]... [--out DIR]
```

`--url` accepts an mcp-index URL or a single toolset endpoint. Cases come from
`--file`, else `--sheet-id`/`SPREADSHEET_ID`. Runs are concurrent
(`--workers`, default 2, bounded by a semaphore to respect Mistral rate limits)
and results stay in input order. `MISTRAL_API_KEY` is read from the environment
or `.env`. See the README for the full option list.

## CI

`.github/workflows/evals.yml` runs on `workflow_dispatch` only. It:

1. syncs the workspace,
2. serves the chosen toolset locally (`TOOLSET=<input> mcp-serve` on :8000) so
   the run needs no live cluster — point `--url` at a deployed index instead if
   you'd rather hit production,
3. runs `mcp-evals run` against the sheet,
4. uploads `outputs/` as an artifact.

Inputs: `toolset`, `group`, `gid`, `sample`, `workers` (passed via env, not
`${{ }}` interpolation, to avoid shell quoting/injection issues). Secrets:
`MISTRAL_API_KEY`, `SPREADSHEET_ID`, and optionally `CDS_TOKEN` (injected as the
`x-cds-token` credential when present).

## Extending it

- **New deterministic check** — add a `score_*` helper in `scoring.py`, a field
  on `Scores`, include it in `present`, and surface it in `report.py`. Drive it
  from a new optional column on `EvalCase`.
- **Different / additional judge** — `make_judge` builds the chain; swap the
  model or `with_structured_output` schema there. (A non-Mistral judge would add
  a provider dependency and secret.)
- **Multi-turn cases** — `run_turn` already threads message history; the runner
  passes `[]` today. A multi-turn case would feed prior turns in instead.
- **Per-set tabs** — if a single tab grows unwieldy, reintroduce a name→gid
  registry in `config.py` and select with an `--eval-set` flag (the gnw-evals
  pattern); the loader/scorer are agnostic to where rows come from.

## Verification

- Unit tests (no network/LLM): `uv run pytest packages/mcp-evals` — CSV/list
  parsing, `status=skip` filtering, tool + dataset scoring, trajectory
  extraction, and judge wiring (judge mocked).
- End-to-end (manual): serve a toolset (`TOOLSET=aoi-generator uv run mcp-serve`),
  then `MISTRAL_API_KEY=... uv run mcp-evals run --url http://localhost:8000/mcp
  --file src/mcp_evals/examples/gold.csv --group aoi`. Expect a pass-rate table
  and CSVs in `outputs/`.
