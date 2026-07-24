# Stage 1: build the toolset's UI views (if it has a ui/ project). The Vite
# build writes self-contained bundles into the package's views/ dir; a toolset
# without ui/ — or a non-toolset build like the index (TOOLSET=mcp-runtime) —
# produces an empty /out and is left untouched. Node is a build-time dependency
# only — it never ships in the runtime image.
FROM node:23-bookworm-slim AS ui
ARG TOOLSET
WORKDIR /app
# Copy the whole toolsets/ tree (always present) rather than toolsets/${TOOLSET}/,
# which does not exist when TOOLSET names a packages/ member (e.g. the index).
COPY toolsets/ ./toolsets/
# Build the views, then stage the toolset's src/ (now carrying the built
# views/*.html) under /out. /out is always created, so the builder's overlay
# below is unconditional and a no-op whenever there is nothing to overlay.
RUN mkdir -p /out && \
    if [ -f "toolsets/${TOOLSET}/ui/package.json" ]; then \
        (cd "toolsets/${TOOLSET}/ui" && npm ci && npm run build) && \
        mkdir -p "/out/toolsets/${TOOLSET}" && \
        cp -a "toolsets/${TOOLSET}/src" "/out/toolsets/${TOOLSET}/src"; \
    fi

# Stage 2: build the Python virtualenv, with the built views overlaid onto the
# toolset source so they are packaged into the installed wheel.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ARG TOOLSET
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY . .
COPY --from=ui /out/ ./
RUN uv sync --frozen --no-dev --no-editable --package "${TOOLSET}"

FROM python:3.12-slim-bookworm
ARG TOOLSET
ENV TOOLSET=${TOOLSET} HOST=0.0.0.0 PATH="/app/.venv/bin:$PATH"
COPY --from=builder /app/.venv /app/.venv
EXPOSE 8000
CMD ["mcp-serve"]
