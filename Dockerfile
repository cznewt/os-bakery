# Multi-stage Dockerfile for os-bakery.
#
# Targets:
#   web                — Django + gunicorn. Tiny.
#   worker-packer      — Celery + Packer + qemu/xz, runs x86 / cloud-image
#                        Packer refreshes + the non-ARM bake pipeline.
#   worker-packer-arm  — Celery + Docker CLI. Shells out to the existing
#                        cznewt/packer-arm-tools image (chroot + qemu-aarch64)
#                        for ARM SBC / handheld bakes. Needs --privileged +
#                        the host Docker socket at runtime.
#   worker-esphome     — Celery + esphome (which pulls PlatformIO toolchains
#                        on first compile). For ESPHome microcontroller bakes.
#   worker             — legacy alias for `worker-packer` so older callers
#                        keep working until they pick a more specific target.
#
# Build:
#   docker build --target web               -t os-bakery-web .
#   docker build --target worker-packer     -t os-bakery-worker-packer .
#   docker build --target worker-packer-arm -t os-bakery-worker-packer-arm .
#   docker build --target worker-esphome    -t os-bakery-worker-esphome .

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
# packages = [osbakery, catalog, recipes, builds, infra, tenants] need all
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

ENV GUNICORN_WORKERS=4 \
    GUNICORN_TIMEOUT=60 \
    GUNICORN_BIND=0.0.0.0:8000

CMD ["sh", "-c", "gunicorn osbakery.wsgi:application \
        --bind ${GUNICORN_BIND} \
        --workers ${GUNICORN_WORKERS} \
        --timeout ${GUNICORN_TIMEOUT} \
        --access-logfile - --error-logfile -"]

# ──────────────────────────────────────────────────────────────────────────────
# worker-packer — non-ARM bakes: pulls upstream images, mounts loop devices,
#                 runs salt-call against the rootfs, repacks as .img.xz
# ──────────────────────────────────────────────────────────────────────────────
FROM base AS worker-packer

ARG PACKER_VERSION

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
        sudo \
    && rm -rf /var/lib/apt/lists/*

# HashiCorp Packer — used by the orchestrator for x86 image refreshes
# (Ubuntu cloud-img, Batocera x86_64, etc.). ARM images go through
# packer-arm-tools (next target), not this binary.
RUN curl -fsSL "https://releases.hashicorp.com/packer/${PACKER_VERSION}/packer_${PACKER_VERSION}_linux_amd64.zip" \
        -o /tmp/packer.zip \
    && unzip /tmp/packer.zip -d /usr/local/bin \
    && rm /tmp/packer.zip \
    && packer version

ENV CELERY_CONCURRENCY=2 \
    CELERY_QUEUES=builds-packer,default

CMD ["sh", "-c", "celery -A osbakery worker \
        -n worker-packer@%h -l info \
        -Q ${CELERY_QUEUES} \
        --concurrency ${CELERY_CONCURRENCY}"]

# ──────────────────────────────────────────────────────────────────────────────
# worker-packer-arm — shells out to packer-arm-tools for ARM bakes
# ──────────────────────────────────────────────────────────────────────────────
FROM base AS worker-packer-arm

# Just enough to talk to the host Docker socket + decompress upstream xz.
# The heavy lifting (chroot + qemu-aarch64-static + salt-call) happens
# inside the cznewt/packer-arm-tools container that this worker spawns.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        xz-utils \
        gzip \
        sudo \
        docker.io \
    && rm -rf /var/lib/apt/lists/*

ENV CELERY_CONCURRENCY=1 \
    CELERY_QUEUES=builds-packer-arm

CMD ["sh", "-c", "celery -A osbakery worker \
        -n worker-packer-arm@%h -l info \
        -Q ${CELERY_QUEUES} \
        --concurrency ${CELERY_CONCURRENCY}"]

# ──────────────────────────────────────────────────────────────────────────────
# worker-esphome — ESPHome firmware compile
# ──────────────────────────────────────────────────────────────────────────────
FROM base AS worker-esphome

# esphome bundles PlatformIO; on first compile it downloads the ESP
# toolchain into ~/.platformio (cached on the worker volume).
RUN pip install --no-cache-dir 'esphome>=2025.11.0'

ENV CELERY_CONCURRENCY=2 \
    CELERY_QUEUES=builds-esphome \
    PLATFORMIO_CORE_DIR=/var/lib/osbakery/platformio

CMD ["sh", "-c", "celery -A osbakery worker \
        -n worker-esphome@%h -l info \
        -Q ${CELERY_QUEUES} \
        --concurrency ${CELERY_CONCURRENCY}"]

# ──────────────────────────────────────────────────────────────────────────────
# worker — legacy alias for worker-packer (kept until callers migrate)
# ──────────────────────────────────────────────────────────────────────────────
FROM worker-packer AS worker
ENV CELERY_QUEUES=builds-packer,builds,default
