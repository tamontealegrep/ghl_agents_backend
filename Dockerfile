# One image per company. The code is the same for every company; the image carries that
# company's agents (bundles: compiled flows, agent.yaml, tool plugins) and its shared code.
#
#   docker build --build-arg COMPANY=family_aims -t agents-family-aims .
#
# In local development docker-compose mounts ./bundles and ./shared over the baked copies,
# so edits show up without rebuilding. On Render nothing is mounted: what was baked runs.
FROM python:3.12-slim AS base

# A slow or flaky network at build time (Render) must not fail the build: long timeout, several retries.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

# Dependencies first (read from pyproject.toml) so code changes do not invalidate this layer.
COPY pyproject.toml ./
RUN python -c "import tomllib; print(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > requirements.txt \
    && pip install -r requirements.txt
COPY src ./src
RUN pip install --no-deps .

# The company this image serves (a folder under companies/). Render passes the service's
# environment variables to the build, so setting COMPANY there is enough.
ARG COMPANY
RUN test -n "$COMPANY" || (echo "Set the COMPANY build argument (a folder under companies/)." >&2; exit 1)
COPY companies/${COMPANY}/bundles /app/bundles
COPY companies/${COMPANY}/shared /app/shared

# Non-root runtime user; bundles/ must be writable for the local sessions.db fallback.
RUN useradd --create-home --uid 10001 agent \
    && chown -R agent:agent /app/bundles
USER agent

ENV COMPANY=${COMPANY} \
    HOST=0.0.0.0 \
    PORT=8010 \
    AGENTS_DIR=/app/bundles

EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os,urllib.request as u; u.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=4)"

CMD ["python", "-m", "agent_backend"]
