# Comparison: mcp-toolsets/cds vs. CliDyn/copernicus-mcp

This document compares two approaches to building an MCP interface to Copernicus Climate Data Store (CDS) and related services.

## Quick Comparison

| Aspect | mcp-toolsets/cds | copernicus-mcp |
|--------|------------------|----------------|
| **Deployment** | Stateless hosted FastMCP streamable-HTTP service | Local stdio MCP server |
| **Scope** | CDS only (Climate Data Store) | CDS, ADS, EWDS, CMEMS marine (two backends) |
| **Tool count (CDS)** | 8 | 9 + status diagnostic |
| **SDK** | Raw `httpx.AsyncClient` | Official `cdsapi` SDK + `copernicusmarine` SDK |
| **Discovery** | Live catalogue API queries | Offline bundled JSON snapshots + 47 curated groups |
| **Caching & Provenance** | None (returns href + metadata) | Local file cache + MD5 sidecars + idempotent re-use |
| **Pre-flight estimation** | ❌ | ✅ (`cds_estimate_request`) |
| **Request cancellation** | ❌ | ✅ (`cds_cancel_request`) |
| **Multi-store support** | Single CDS endpoint | Per-store routing (CDS/ADS/EWDS) |
| **Authentication** | `CDS_API_KEY` env var → `PRIVATE-TOKEN` header | Same, or `cdsapi` defaults to `~/.cdsapirc` |

## This Repository: mcp-toolsets/cds

### Architecture & Deployment
- Part of a **monorepo of stateless MCP toolsets**, each deployed as its own k8s Service
- Uses `packages/mcp-runtime` (shared FastMCP server runner) + `charts/mcp-toolset` (k8s Helm chart)
- Multi-tenant, with no local filesystem access — suitable for shared/cloud deployments
- Stateless: requests → responses; no job tracking or file downloads on the server

### Transport & SDK
- **No `cdsapi` dependency** — instead uses raw `httpx.AsyncClient` against CDS Toolbox/Processes (OGC API - Processes) REST endpoints directly
- Direct endpoints:
  - Catalogue: `https://cds.climate.copernicus.eu/api/catalogue/v1`
  - Retrieve: `https://cds.climate.copernicus.eu/api/retrieve/v1`
- Custom retry logic via `tenacity` (3 attempts, exponential backoff 2–10s)
- Custom error classification (`_errors.py`): `auth`, `licence`, `queue_limit`, `bad_request`, `not_found`, `not_ready`, `transient`

### Tools Exposed (8 functions)

| Tool | Purpose | Key Parameters |
|------|---------|-----------------|
| `search_datasets` | Catalogue keyword search | `query: str` |
| `get_dataset_schema` | Dataset input parameters & types | `dataset: str` |
| `apply_constraints` | Valid values given partial request | `dataset: str, partial_request: dict` |
| `submit_request` | Queue async retrieval | `dataset: str, request: dict` |
| `get_job_status` | Poll job status | `job_id: str` |
| `get_results` | Get download link/metadata | `job_id: str` |
| `list_jobs` | List jobs, optionally filtered | `status: list[str] \| None, limit: int` |
| `check_credentials` | Validate API key | (no parameters) |

All are async LangChain `@tool` decorated functions returning structured `dict` or `list[dict]`, never raising exceptions (errors returned as structured dicts).

### Authentication
- `CDS_API_KEY` environment variable (or `.env` file via pydantic-settings)
- Sent as HTTP header `PRIVATE-TOKEN: <key>`
- In k8s: secret `cds-credentials` referenced in `toolset.yaml` → injected via `envFrom`
- Validated by `check_credentials` (calls `GET /jobs?limit=1`)

### Data Flow
- **Submit**: `submit_request` → returns `{job_id, status, ...}` immediately (async server-side queuing)
- **Poll**: `get_job_status` → returns `{status, created, started, finished, results_ready, ...}`
- **Download**: `get_results` (once status is `successful`) → returns `{href, content_type, size, checksum}` (client downloads the href)
  - **No server-side file download or cache** — response is metadata + external URI

### Scope
- **CDS only** (no ADS/EWDS or CMEMS marine)
- **Dataset-agnostic** — works with any dataset ID registered in the CDS catalogue (ERA5, CERRA, CMIP6, etc.) without hardcoding support for each one
- Discovery via live `search_datasets` call to CDS catalogue API (always current, simple, but depends on CDS API availability)

---

## copernicus-mcp

### Architecture & Deployment
- **Local stdio MCP server** — designed to run on user's machine (Claude Desktop, Claude Code with `copernicus-mcp serve`)
- Two backends (`registry.py` + `protocol.py`) — **CMEMS** (marine) and **CDS family** (CDS/ADS/EWDS)
- Shared `orchestrator` pattern abstracts backend differences
- Persistent local filesystem: cache directory for downloads, workflow tracking DB, provenance sidecars

### Transport & SDK
- **Uses official SDKs**:
  - `cdsapi` (Apache 2.0, from ECMWF) for CDS/ADS/EWDS
  - `copernicusmarine` (EUPL-1.2, from Mercator Ocean) for CMEMS
- CDS backend (`_make_cdsapi_client`):
  - Constructs `cdsapi.Client` with per-store endpoint routing
  - Single PAT works across all three stores (CDS/ADS/EWDS), each with its own HTTP endpoint
  - Sync SDK wrapped in `asyncio.to_thread()` for async/await integration
  - Retry capped at `retry_max=3, sleep_max=10`
- CMEMS backend similarly wraps the marine SDK
- Both SDKs abstract away some implementation details (e.g., `cdsapi` handles ToU cookie flows internally)

### Tools Exposed for CDS/ADS/EWDS (9 functions + 1 diagnostic)

| Tool | Purpose | Key Parameters |
|------|---------|-----------------|
| `cds_search_groups` | Hierarchical discovery (curated groups) | `query: str \| None, top_k: int \| None` |
| `cds_search_datasets` | Search catalogue + filter | `keyword, store, bbox, time_range, variable, domain, category, limit` |
| `cds_describe_dataset` | Full STAC metadata | `dataset_id: str` |
| `cds_apply_constraints` | Valid values given partial request | `dataset_id: str, inputs: dict` |
| `cds_estimate_request` | **Heuristic size + queue tier estimate** | Same shape as `submit_request` |
| `cds_submit_request` | Queue retrieval (requires `confirmed` flag) | `dataset_id, inputs, confirmed: bool` |
| `cds_check_request_status` | Poll job status | `request_id: str` |
| `cds_download_request_result` | Resolve cached file (if successful) | `request_id: str, target: str \| None` |
| `cds_cancel_request` | **Cancel in-flight request (best-effort)** | `request_id: str` |
| `copernicus_mcp_status` | Diagnostic (backend info, cache status) | (no parameters) |

### Discovery Pattern
- **Offline hierarchical**:
  1. `cds_search_groups` → browse 47 hand-curated domain/category groups (no API call)
  2. `cds_search_datasets` → filter catalogue snapshot by keyword/filters (local JSON search, not live API)
  3. `cds_describe_dataset` → fetch full STAC metadata from CDS (API call, but specific dataset only)
- Bundled JSON catalogue snapshots committed to the repo — fast, deterministic, no live API dependency
- Maintains 47 curated routing groups (e.g., "Reanalysis", "Satellite observations", "Seasonal forecasts")
- Phrase-matching for search (not embeddings)

### Authentication
- `CDSAPI_KEY` environment variable (or `~/.cdsapirc` as cdsapi default)
- Extracted by `CdsApiKeyAdapter`
- Flows through `_make_cdsapi_client` to the SDK
- Credentials never stored by the MCP server itself

### Data Flow
- **Estimate**: `cds_estimate_request` → `{estimated_size_bytes, queue_latency_tier, epistemic_status}`
  - Heuristic only (~±50% accuracy)
  - Helps user confirm before submitting
- **Submit**: `cds_submit_request` → requires `confirmed: bool` flag
  - Handles `TermsNotAcceptedError` and extracts ToU policy recovery URL
  - Deduplicates cache hits and in-flight requests
  - Returns `{status, request_id, cache_key, result_uri}`
- **Poll**: `cds_check_request_status` → `{status, timestamps, error_details, cached_file_descriptor}`
- **Download**: `cds_download_request_result` (once successful)
  - **Server-side download** via `client.client.download_results()`
  - Magic-byte verification (sniffs GRIB/NetCDF/etc. format)
  - Atomic cache commit + workflow row persistence
  - Returns `{filepath, uri, cache_key, metadata, provenance}`

### Caching & Provenance
- **Local persistent cache** (platform-specific: `~/.cache/copernicus-mcp` on Linux)
- **Idempotent re-use**: cached results returned without re-downloading
- **In-flight deduplication**: concurrent identical requests share one download
- **MD5 provenance sidecars**: JSON metadata files tracking request, response, timestamps
- **Workflow tracking**: database rows linking `request_id` → cache entry → provenance

### Scope
- **Multi-store**: Supports CDS, ADS (Atmosphere Data Store), EWDS (Emergency Weather Data Store)
  - One PAT; per-store endpoint routing handles the differences
- **Plus CMEMS marine**: 1,251 datasets/306 products (entire separate backend)
- **Generic over datasets**, just like this repo's CDS toolset

---

## Key Differences & Tradeoffs

### 1. **Deployment Model (Root Divergence)**
- **This repo**: Stateless hosted service, multi-tenant, no local filesystem
  - ✅ Suitable for shared cloud environments
  - ✅ Horizontal scaling (stateless, load-balancer friendly)
  - ❌ Cannot store files locally or cache downloads
  - ❌ Every result-fetch is a new download from CDS servers
- **copernicus-mcp**: Local stdio server with persistent cache
  - ✅ Idempotent results, offline-capable once cached
  - ✅ File provenance tracking via sidecars
  - ❌ Tied to one user's machine / local filesystem
  - ❌ No multi-user sharing without external storage backend

This difference explains most other architectural choices (href return vs. file download, presence/absence of provenance, etc.).

### 2. **SDK Choice**
- **httpx (this repo)**
  - ✅ Full async/await control (no thread wrapping needed)
  - ✅ Custom retry logic + error taxonomy fit hosted-service constraints
  - ❌ Reimplements CDS API details (endpoint routing, ToU-rejection detection)
  - ❌ Less battle-tested than official libraries
- **cdsapi (copernicus-mcp)**
  - ✅ Official ECMWF library; less reinvention of CDS protocol details
  - ✅ Better handles ToU/licence flows via internal cookie management
  - ❌ Sync library wrapped in `asyncio.to_thread()` (thread pool overhead)
  - ❌ Couples to CDS SDK's public API surface (less control)

### 3. **Discovery Strategy**
- **Live catalogue API (this repo)**
  - ✅ Always current (reflects latest datasets/parameters in CDS)
  - ✅ Simple: just call the API and filter results
  - ❌ Depends on CDS API availability at runtime
  - ❌ Less predictable (API changes might break parsing)
- **Offline curated snapshots (copernicus-mcp)**
  - ✅ Fast, deterministic, no runtime API dependency
  - ✅ Curated grouping (47 routing groups) guides discovery
  - ❌ Requires maintenance — catalogue snapshots rot over time
  - ❌ New datasets don't appear until someone updates the bundled snapshots

### 4. **Scope**
- **This repo**: CDS only, dataset-agnostic
  - Focused, maintainable, but doesn't cover ADS/EWDS/CMEMS
- **copernicus-mcp**: CDS + ADS + EWDS + CMEMS marine
  - Broader coverage, but significantly larger codebase + two separate backend implementations

### 5. **Capabilities Present in copernicus-mcp but Missing Here**

| Feature | This Repo | copernicus-mcp | Notes |
|---------|-----------|---|-------|
| Pre-flight size estimation | ❌ | ✅ (`cds_estimate_request`) | Heuristic ~±50% accuracy; helps user confirm before submitting |
| Request cancellation | ❌ | ✅ (`cds_cancel_request`) | Best-effort; DELETE `/jobs/{id}` |
| Multi-store routing | ❌ | ✅ | ADS, EWDS, CDS via single PAT |
| ToU rejection + recovery URL | ❌ | ✅ | Detected via error message parsing; extracts policy link |
| Result caching & provenance | ❌ | ✅ | Local cache + MD5 sidecars + idempotent re-use |
| Offline discovery | ❌ | ✅ | Bundled catalogue snapshots + 47 groups |

### 6. **Possible Future Enhancements** (Additive, Non-Breaking)

If this repo's CDS toolset were to adopt features from copernicus-mcp:

1. **`estimate_request` tool** (low effort, high value)
   - Add a heuristic estimation endpoint (not all datasets support this, but many do)
   - Could be implemented as a tool without changing the httpx-based architecture
   - Returns `{estimated_size_bytes, queue_tier}`

2. **`cancel_request` tool** (low effort, low value)
   - DELETE `/jobs/{id}` on the CDS retrieve API
   - Covers a small use case (user wants to stop a job they submitted)

3. **Multi-store support** (moderate effort)
   - Extend `settings.py` with per-store base URLs (CDS/ADS/EWDS)
   - Route `submit_request` by dataset ID → determine store → use correct endpoint
   - Would require maintaining a dataset-to-store mapping (or detecting at runtime)

4. **Offline discovery + curated groups** (higher effort, medium value)
   - Requires maintaining bundled JSON catalogue snapshots
   - Would need a process to update snapshots as CDS catalogue evolves
   - Adds ~47 routing groups for hierarchical discovery
   - Trade-off: faster discovery at the cost of staleness

5. **Local caching + provenance** (high effort, architecture change)
   - Requires local filesystem access (breaks stateless-service model)
   - Would need a shared storage backend for multi-replica deployments
   - Not recommended for this repo's hosted-service design

---

## Recommendations

1. **For this repository's use case (hosted k8s service)**: current httpx-based approach is sound
   - Simple, stateless, scalable
   - Adding `estimate_request` and `cancel_request` tools is a low-cost improvement
   - Live catalogue search is acceptable; if staleness becomes a problem, consider a hybrid (periodic snapshot + live fallback)

2. **For local/single-user deployments**: copernicus-mcp is more feature-complete
   - Caching, provenance, offline discovery all valuable for reproducibility
   - Broader scope (CMEMS marine, multi-store) if those datasets matter
   - Official SDK usage reduces long-term maintenance burden

3. **Coexistence**: Both approaches are valid for different deployment contexts
   - This repo's CDS toolset excels in cloud/k8s environments
   - copernicus-mcp excels for local reproducible research workflows
   - A user might use both: fetch catalogue/schema from this hosted service for speed, then fall back to local copernicus-mcp for offline data access if needed
