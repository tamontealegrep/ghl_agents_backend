# One image for every agent. Agents are NOT baked in: mount the bundles directory
# (generated flows + agent.yaml + tool plugins) at /app/bundles, or at AGENTS_DIR.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first (read from pyproject.toml) so code changes do not invalidate this layer.
COPY pyproject.toml ./
RUN python -c "import tomllib; print(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > requirements.txt \n    && pip install -r requirements.txt
COPY src ./src
RUN pip install --no-deps .

# Non-root runtime user; bundles/ must be writable for the local sessions.db fallback.
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /app/bundles \
    && chown -R agent:agent /app/bundles
USER agent

ENV HOST=0.0.0.0 \
    PORT=8010 \
    AGENTS_DIR=/app/bundles

EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os,urllib.request as u; u.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=4)"

CMD ["python", "-m", "agent_backend"]
