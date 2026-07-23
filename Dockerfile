# Stage 1: build the toolset's UI views (if it has a ui/ project). The Vite
# build writes self-contained bundles into the package's views/ dir; a toolset
# without ui/ skips this untouched. Node is a build-time dependency only — it
# never ships in the runtime image.
FROM node:23-bookworm-slim AS ui
ARG TOOLSET
WORKDIR /app
COPY toolsets/${TOOLSET}/ ./toolsets/${TOOLSET}/
RUN if [ -f "toolsets/${TOOLSET}/ui/package.json" ]; then \
        cd "toolsets/${TOOLSET}/ui" && npm ci && npm run build; \
    fi

# Stage 2: build the Python virtualenv, with the built views overlaid onto the
# toolset source so they are packaged into the installed wheel.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ARG TOOLSET
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY . .
COPY --from=ui /app/toolsets/${TOOLSET}/src/ ./toolsets/${TOOLSET}/src/
RUN uv sync --frozen --no-dev --no-editable --package "${TOOLSET}"

FROM python:3.12-slim-bookworm
ARG TOOLSET
ENV TOOLSET=${TOOLSET} HOST=0.0.0.0 PATH="/app/.venv/bin:$PATH"
COPY --from=builder /app/.venv /app/.venv
EXPOSE 8000
CMD ["mcp-serve"]
