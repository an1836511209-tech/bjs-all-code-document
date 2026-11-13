# syntax=docker/dockerfile:1.6

FROM python:3.10-slim AS builder

WORKDIR /app

# 1. 换 apt 源为清华（兼容 Debian Trixie 的 debian.sources 与旧版 sources.list）
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
        sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
        sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list && \
        sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list; \
    fi

# 2. 安装系统依赖和 Poetry
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir poetry==2.1.2 \
    && pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=0 \
    POETRY_VIRTUALENVS_CREATE=0 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

COPY pyproject.toml poetry.lock ./

# 3. 配置 Poetry 使用国内源
RUN --mount=type=cache,target=/tmp/poetry_cache \
    --mount=type=cache,target=/root/.cache/pip \
    poetry config repositories.tuna https://pypi.tuna.tsinghua.edu.cn/simple \
    && poetry install --no-root --only main

FROM python:3.10-slim
WORKDIR /app

# 换 apt 源为清华（兼容 Debian Trixie 的 debian.sources 与旧版 sources.list）
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
        sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
        sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list && \
        sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list; \
    fi

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    fontconfig \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY src/ ./src/
COPY config/ ./config/
COPY README.md ./
COPY data/rule_configs/ ./data/rule_configs/
COPY data/region_data.json data/disclosure_dictionaries.json ./data/
COPY PP-LCNet_x1_0_doc_ori/ ./PP-LCNet_x1_0_doc_ori/

RUN mkdir -p logs data/uploads data/temp

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8580 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    NO_PROXY="*" \
    no_proxy="*"

EXPOSE 8580

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8580/health')" || exit 1

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8580", "--workers", "1"]
