# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./

# --- Development image -----------------------------------------------------
FROM base AS dev
RUN pip install -r requirements-dev.txt
COPY . .
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# --- Production image ------------------------------------------------------
FROM base AS prod
RUN pip install -r requirements.txt
COPY . .

# Collected at build time so the container starts with its static manifest
# already in place. It needs no database: every setting it reads has a default.
RUN python manage.py collectstatic --noinput

EXPOSE 8000

# Shell form on purpose: the platform injects PORT at runtime, and binding a
# hard-coded port makes the service unreachable however healthy it is.
# WEB_CONCURRENCY is gunicorn's own variable, so worker count is tunable
# without a rebuild. Logs go to stdout/stderr for the platform to collect.
CMD gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --access-logfile - \
    --error-logfile -
