FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ARG TOOLSET
ARG CDS_EQC_S3_URI
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev --no-editable --package "${TOOLSET}"
RUN if [ "${TOOLSET}" = "cds" ] && [ -n "${CDS_EQC_S3_URI:-}" ]; then \
      cd toolsets/cds && CDS_EQC_S3_URI="${CDS_EQC_S3_URI}" uv run python scripts/eqc_snapshot.py pull; \
    fi

FROM python:3.12-slim-bookworm
ARG TOOLSET
ENV TOOLSET=${TOOLSET} HOST=0.0.0.0 PATH="/app/.venv/bin:$PATH"
ENV EQC_DATA_DIR=/app/data/eqc EQC_INDEX_DIR=/app/data/eqc_index
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/toolsets/cds/data /app/data
EXPOSE 8000
CMD ["mcp-serve"]
