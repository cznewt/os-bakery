# Multi-stage Dockerfile for os-bakery.
#
# Two targets:
#   * web     — Django + gunicorn. Tiny.
#   * worker  — Django + Celery + the build toolchain (Packer, qemu, xz, salt-call).
#
# Build:
#   docker build --target web    -t os-bakery-web    .
#   docker build --target worker -t os-bakery-worker .

ARG PYTHON_VERSION=3.12
ARG PACKER_VERSION=1.11.2

# ──────────────────────────────────────────────────────────────────────────────
# base — shared Python layer with the app installed
# ──────────────────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=osbakery.settings

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the whole source tree before `pip install .` — hatchling's
# packages = [osbakery, catalog, recipes, builds, infra] need all five
# top-level dirs present at build time.
COPY . /app

RUN pip install --upgrade pip \
    && pip install gunicorn \
    && pip install .

# Collect static (no DB required because we set a noop DATABASE_URL via env).
RUN DJANGO_SECRET_KEY=build-time-dummy DATABASE_URL=sqlite:////tmp/build.sqlite3 \
    python manage.py collectstatic --noinput \
    && rm -f /tmp/build.sqlite3

# ──────────────────────────────────────────────────────────────────────────────
# web — gunicorn-serving Django
# ──────────────────────────────────────────────────────────────────────────────
FROM base AS web

EXPOSE 8000

# Sensible production defaults; override via env at deploy time.
ENV GUNICORN_WORKERS=4 \
    GUNICORN_TIMEOUT=60 \
    GUNICORN_BIND=0.0.0.0:8000

CMD ["sh", "-c", "gunicorn osbakery.wsgi:application \
        --bind ${GUNICORN_BIND} \
        --workers ${GUNICORN_WORKERS} \
        --timeout ${GUNICORN_TIMEOUT} \
        --access-logfile - --error-logfile -"]

# ──────────────────────────────────────────────────────────────────────────────
# worker — Celery + build toolchain
# ──────────────────────────────────────────────────────────────────────────────
FROM base AS worker

ARG PACKER_VERSION

# Tools needed by builds.orchestrator when it does real mounting + packing.
# libguestfs is intentionally omitted from the slim image: it pulls in a
# kernel and grows the layer by ~600 MB. Add it in your deployment overlay
# if you need guestmount (or run the worker on a host with kpartx/losetup).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        xz-utils \
        gzip \
        unzip \
        zip \
        qemu-utils \
        kpartx \
        dosfstools \
        e2fsprogs \
        parted \
        salt-common \
        sudo \
    && rm -rf /var/lib/apt/lists/*

# Install Packer.
RUN curl -fsSL "https://releases.hashicorp.com/packer/${PACKER_VERSION}/packer_${PACKER_VERSION}_linux_amd64.zip" \
        -o /tmp/packer.zip \
    && unzip /tmp/packer.zip -d /usr/local/bin \
    && rm /tmp/packer.zip \
    && packer version

ENV CELERY_CONCURRENCY=2 \
    CELERY_QUEUES=builds,default

CMD ["sh", "-c", "celery -A osbakery worker \
        -l info \
        -Q ${CELERY_QUEUES} \
        --concurrency ${CELERY_CONCURRENCY}"]
