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

Environment:

- `EQC_DATA_DIR` (default `toolsets/cds/data/eqc`, relative to the cds package)
- `EQC_INDEX_DIR` (default `toolsets/cds/data/eqc_index`)
- `CDS_EQC_S3_URI` — optional `s3://bucket/prefix/` for snapshot pull/push

```bash
uv run python scripts/eqc_snapshot.py pull   # seed from S3
uv run python scripts/eqc_snapshot.py push   # upload latest.tar.gz
```

Weekly refresh: `.github/workflows/cds-eqc-data.yml` (set repo variable `CDS_EQC_S3_URI`).

Docker builds for the `cds` toolset copy `toolsets/cds/data/` into the image when present, or pull from S3 when `CDS_EQC_S3_URI` is set at build time.
