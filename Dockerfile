# Python and uv digests verified from their official registries during P18.
FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254
COPY --from=ghcr.io/astral-sh/uv:0.12.2@sha256:069a51314a7bb6031777a9273205fe1b0b19e914ef418207d1338b268df641dd /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never HF_HOME=/opt/model-cache \
    RAG_EMBEDDING_REVISION=e8f8c211226b894fcb81acc59f3b34ba3efd5f42
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY app ./app
COPY data/knowledge ./data/knowledge
ENV PATH="/app/.venv/bin:$PATH"
RUN python -m app.deployment.prepare_model
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 LANGGRAPH_STRICT_MSGPACK=true
ENV APP_ENV=production AUTH_MODE=auth0 API_DOCS_ENABLED=false METRICS_ENABLED=false
RUN groupadd --gid 10001 travel && useradd --uid 10001 --gid travel --create-home travel \
    && mkdir -p /app/data/generated && chown -R travel:travel /app/data/generated
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "app.deployment.start"]
