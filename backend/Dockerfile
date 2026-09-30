# --- CineMind backend (FastAPI + uvicorn) ------------------------------------
# Multi-stage: builder installs deps into a venv, runtime copies the venv and
# app source. No compilers needed at runtime.

# --- Stage 1: builder ---------------------------------------------------------
FROM python:3.12-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

# --- Stage 2: runtime ---------------------------------------------------------
FROM python:3.12-slim AS runtime
# security updates + curl for the container healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"
RUN groupadd -r cinemind && useradd -r -g cinemind cinemind
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --chown=cinemind:cinemind app ./app
COPY --chown=cinemind:cinemind alembic ./alembic
COPY --chown=cinemind:cinemind alembic.ini ./
USER cinemind
EXPOSE 8000
# Migrations run via Render's preDeploy command (or manually); the container
# just serves. PORT is injected by Render; docker-compose-style local runs
# default to 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --workers ${WEB_CONCURRENCY:-1}"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT:-8000}/health || exit 1
