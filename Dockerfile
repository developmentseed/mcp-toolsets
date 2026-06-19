FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ARG TOOLSET
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev --no-editable --package "${TOOLSET}"
# Always create the dir so the COPY below succeeds for every toolset. For the
# cds image the EQC corpus + index (incl. the bundled model) arrives via the
# build context: CI downloads the eqc-data artifact into toolsets/cds/data
# before the build, and the COPY . . above brings it in.
RUN mkdir -p toolsets/cds/data

FROM python:3.12-slim-bookworm
ARG TOOLSET
ENV TOOLSET=${TOOLSET} HOST=0.0.0.0 PATH="/app/.venv/bin:$PATH"
ENV EQC_DATA_DIR=/app/data/eqc EQC_INDEX_DIR=/app/data/eqc_index
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/toolsets/cds/data /app/data
EXPOSE 8000
CMD ["mcp-serve"]
