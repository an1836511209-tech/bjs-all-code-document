ARG UV_VERSION=0.7.20

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=30000 \
    UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY apps/data_mcp/pyproject.toml apps/data_mcp/README.md ./apps/data_mcp/
COPY apps/report_agent/pyproject.toml apps/report_agent/README.md ./apps/report_agent/
COPY apps/data_mcp/src ./apps/data_mcp/src
COPY contracts ./contracts
COPY resources/reference_data ./resources/reference_data
COPY deploy/environments ./deploy/environments

RUN --mount=type=cache,target=/root/.cache/uv \
    sed -i 's|https://files.pythonhosted.org/packages|https://mirrors.aliyun.com/pypi/packages|g' uv.lock \
    && uv sync --frozen --package bjs-data-mcp --no-dev --no-editable \
    && groupadd --gid 10002 data-mcp \
    && useradd --uid 10002 --gid 10002 --no-create-home --shell /usr/sbin/nologin data-mcp

ENV PATH="/app/.venv/bin:${PATH}"
USER data-mcp

EXPOSE 8001
CMD ["data-mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8001"]
