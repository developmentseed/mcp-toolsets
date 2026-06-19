# mcp-evals

Evaluation harness for the mcp-toolsets agent. It loads eval cases (from a
Google Sheet or a local CSV), runs the [`mcp-agent`](../mcp-agent) against each
query, and scores its **tool use** and **answer quality**. Results are written
as CSVs and summarised in the console.

It reuses the agent itself (`mcp_agent.main.build_agent` / `run_turn`) rather
than reimplementing it, so an eval run exercises the exact code path a user
hits. There is no agent API to call — the agent runs in-process.

For the design rationale, architecture, and extension points, see
[docs/evaluation-framework.md](docs/evaluation-framework.md).

## Running

```sh
# Against a locally served toolset, using the bundled example cases
TOOLSET=aoi-generator uv run mcp-serve            # one shell
MISTRAL_API_KEY=... uv run mcp-evals run \
  --url http://localhost:8000/mcp \
  --file src/mcp_evals/examples/gold.csv --group aoi

# Against the shared Google Sheet (see "Eval data" below)
SPREADSHEET_ID=... MISTRAL_API_KEY=... uv run mcp-evals run --url http://localhost:8000/mcp
```

Key options (`mcp-evals run --help`): `--url` (MCP index or single endpoint),
`--file` / `--sheet-id` / `--gid` (where cases come from), `--group` (filter),
`--sample` (cap), `--workers` (concurrency), `--credential "Header: value"`
(per-toolset secret injected over the MCP transport, e.g.
`-c 'x-cds-token: ...'`), `--out` (CSV directory, default `outputs/`).

`MISTRAL_API_KEY` is required (drives both the agent and the judge) and is read
from the environment or a `.env` file, like `mcp-agent`.

## Eval data

Cases live in **one tab** of a Google Sheet, shared "anyone with the link can
view" so it can be read via its CSV export URL with no credentials. Pass the id
as `--sheet-id` or set `SPREADSHEET_ID`. A local CSV with the same columns
(`--file`) works identically — see `src/mcp_evals/examples/gold.csv`.

| column | required | meaning |
|---|---|---|
| `test_id` | ✓ | stable id, e.g. `cds-search-001` |
| `group` | | category (often the toolset); filter with `--group`, grouped in the report |
| `query` | ✓ | the user message (single turn) |
| `expected_answer` | | acceptance criteria in plain language; graded **semantically** by the Mistral judge |
| `expected_dataset_ids` | | **comma**-separated ids, any one acceptable; must surface in tool args or the answer |
| `expected_tools` | | **semicolon**-separated tool names that must be called |
| `forbidden_tools` | | **semicolon**-separated tool names that must not be called |
| `status` | | blank = active; `skip` = excluded |
| `notes` | | free text for collaborators; ignored by code |

Fill in only the dimensions you care about per row: an empty expected column is
excluded from that case's score. Unknown extra columns (priority, author, …)
are preserved and ignored, so the sheet can grow without code changes.

## Scoring

Each dimension is `1` / `0`, or `None` when the case sets no expectation for it:

- **tool_score** — every `expected_tools` called and no `forbidden_tools` called.
- **dataset_score** — any `expected_dataset_ids` appears (case-insensitive) in a
  tool call's arguments or the final answer.
- **answer_score** — a Mistral judge grades the answer against `expected_answer`
  for semantic equivalence.

`overall` is the mean of the present (non-`None`) scores; a case **passes** at
`overall >= 0.7`. The console prints a per-case table plus overall and per-group
pass rates; `outputs/<timestamp>_summary.csv` and `_detailed.csv` hold the full
results (the detailed file includes expected-vs-actual and the judge's reason).

## CI

The repo-level **Evals** workflow (`.github/workflows/evals.yml`) runs this on
demand (`workflow_dispatch`): it serves the chosen toolset, runs the suite
against the sheet, and uploads the CSVs as an artifact. Secrets:
`MISTRAL_API_KEY`, `SPREADSHEET_ID`, and optionally a toolset credential
(`CDS_TOKEN`). It is intentionally not part of PR/push CI.
