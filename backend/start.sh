#!/bin/sh
# CineMind container entrypoint: migrate, then serve.
#
# Render Docker services don't support a blueprint preDeploy hook, so
# migrations run here on every boot. Alembic is idempotent (a no-op when
# the schema is current), so restarts and multi-worker boots are safe.
set -e

echo "[entrypoint] running migrations (alembic upgrade head)..."
alembic upgrade head

echo "[entrypoint] starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --workers "${WEB_CONCURRENCY:-1}"
