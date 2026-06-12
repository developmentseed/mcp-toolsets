"""LangChain tools for the Copernicus Climate Data Store (CDS).

Covers the full retrieval workflow: search the catalogue, inspect a
dataset's schema and constraints, submit requests, then poll jobs and
fetch download links.

Retrieve-API tools act as the calling user: their CDS key arrives as the
`x-cds-token` HTTP header on each MCP request (advertised below via
``CREDENTIAL_HEADERS``). Only `search_datasets` (public catalogue) works
without it.
"""

from ..client import CDS_TOKEN_HEADER
from .apply_constraints import apply_constraints
from .check_credentials import check_credentials
from .get_dataset_schema import get_dataset_schema
from .get_job_status import get_job_status
from .get_results import get_results
from .list_jobs import list_jobs
from .search_datasets import search_datasets
from .submit_request import submit_request

__all__ = [
    "CREDENTIAL_HEADERS",
    "TOOLS",
    "apply_constraints",
    "check_credentials",
    "get_dataset_schema",
    "get_job_status",
    "get_results",
    "list_jobs",
    "search_datasets",
    "submit_request",
]

TOOLS = [
    search_datasets,
    get_dataset_schema,
    apply_constraints,
    submit_request,
    get_job_status,
    get_results,
    list_jobs,
    check_credentials,
]

# Advertised via /health and the index: clients send this credential to this
# toolset's connection only, never to unrelated toolsets.
CREDENTIAL_HEADERS = [CDS_TOKEN_HEADER]
