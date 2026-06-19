# EQC corpus pipeline

Offline fetch, semantic index, and MCP tools for CDS quality-assurance (EQC) discovery.

## Tools

- `search_eqc(query)` — semantic search over baked EQC prose (one document per dataset)
- `get_dataset_eqc(dataset_id)` — full EQC prose + QA pass count for one dataset

Both read `data/eqc/` and `data/eqc_index/` only; no live CDS calls at query time.

## Refresh corpus

```bash
cd toolsets/cds
uv run python scripts/fetch_eqc_corpus.py --workers 2
```

`fetch_eqc_corpus.py` writes the whole `data/` tree: `eqc/index.json`, one
`eqc/<id>.md` per dataset, the raw `eqc/raw/<id>.json` snapshots, and the
`eqc_index/` search index (embeddings + the bundled embedding model).

Environment:

- `EQC_DATA_DIR` (default `toolsets/cds/data/eqc`, relative to the cds package)
- `EQC_INDEX_DIR` (default `toolsets/cds/data/eqc_index`)

## Deployment

The `data/` tree is gitignored, so it is shipped into the image via a build
artifact rather than committed:

1. `.github/workflows/cds-eqc-data.yml` (weekly + `workflow_dispatch`) rebuilds
   the corpus, sanity-checks it, and uploads `toolsets/cds/data/` as the
   `eqc-data` artifact.
2. `.github/workflows/deploy.yml` downloads the latest successful `eqc-data`
   artifact into `toolsets/cds/data/` before building the cds image (falling
   back to an inline build if no artifact exists yet). `COPY . .` then bakes it
   in; the bundled `eqc_index/model/` keeps the image offline (no HuggingFace
   call at build or runtime).

The deploy workflow only rebuilds the cds image when cds files change, so a
fresh weekly artifact reaches the image on the next cds build — trigger
`deploy.yml` via `workflow_dispatch` to ship refreshed EQC data without a code
change.
