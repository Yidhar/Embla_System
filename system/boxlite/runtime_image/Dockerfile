FROM python:3.11-slim

ARG EMBLA_RUNTIME_ASSET_NAME=embla_py311_default

LABEL org.opencontainers.image.title="Embla BoxLite Runtime"
LABEL org.opencontainers.image.description="Embla default BoxLite execution runtime for Python 3.11 sessions"
LABEL org.opencontainers.image.version="py311"
LABEL org.opencontainers.image.vendor="Embla System"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EMBLA_RUNTIME_ASSET_NAME=${EMBLA_RUNTIME_ASSET_NAME} \
    PATH=/workspace/.venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        findutils \
        git \
        procps \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*' \
    && ln -sf /usr/local/bin/python3 /usr/local/bin/python

WORKDIR /workspace

CMD ["python", "-V"]
