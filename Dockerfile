FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ARG TOOLSET
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev --no-editable --package "${TOOLSET}"

FROM python:3.12-slim-bookworm
ARG TOOLSET
ENV TOOLSET=${TOOLSET} HOST=0.0.0.0 PATH="/app/.venv/bin:$PATH"
COPY --from=builder /app/.venv /app/.venv
EXPOSE 8000
CMD ["mcp-serve"]
