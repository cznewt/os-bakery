# Deployment

## Components to run

| Component     | What it does                                       |
| ------------- | -------------------------------------------------- |
| `gunicorn`    | Serves Django (catalog, recipes, builds API, downloads). |
| `celery`      | Subscribes to the `builds` queue, runs orchestrator. |
| `redis`       | Celery broker + result backend.                    |
| `postgres`    | Persistent state.                                  |
| `nginx`       | TLS termination + static files.                    |
| (optional) `minio` / S3 | Artifact storage.                        |
| (optional) `celery beat` | Cron-style refresh of Packer templates. |

The **Celery worker is special**: it needs root or sudo-without-password access to `losetup`, `mount`, `umount`, `kpartx`, `xz`, `qemu-img`. Run it on a *dedicated build host*.

## Required env

See `.env.example` for the full list. Production overrides:

```
DJANGO_SECRET_KEY=<...random...>
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=bakery.example.com

DATABASE_URL=postgres://osbakery:<pass>@db:5432/osbakery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

ARTIFACT_STORAGE_BACKEND=s3
AWS_STORAGE_BUCKET_NAME=os-bakery-artifacts
AWS_S3_REGION_NAME=eu-central-1
AWS_S3_ENDPOINT_URL=https://s3.eu-central-1.amazonaws.com
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...

PACKER_TEMPLATES_ROOT=/srv/os-bakery/packer
SALT_STATES_ROOT=/srv/os-bakery/salt/states
SALT_PILLAR_ROOT=/srv/os-bakery/salt/pillar
BUILD_WORK_ROOT=/srv/os-bakery/work
DOWNLOAD_TOKEN_TTL_HOURS=168
```

## Bootstrapping

```sh
# 1. Schema
python manage.py migrate

# 2. Seed catalog (manual or via a fixture)
python manage.py shell -c "
from catalog.models import *
arch_arm64, _ = Architecture.objects.get_or_create(slug='arm64', defaults={'name':'ARM 64-bit', 'family':'arm', 'bits':64})
HardwareTarget.objects.get_or_create(slug='rpi5', defaults={'name':'Raspberry Pi 5', 'architecture':arch_arm64, 'boot_method':'rpi', 'soc':'BCM2712'})
"

# 3. Refresh base images
cd packer/batocera/rpi5 && packer build template.pkr.hcl

# 4. Reconcile filesystem + DB
python manage.py sync_filesystem

# 5. Author a recipe + version through the admin or a fixture
```

## Recommended container layout

```
docker compose services:
  web:      gunicorn osbakery.wsgi (read-only filesystem, no privileged ops)
  worker:   celery -A osbakery worker -Q builds (privileged, build tools installed)
  beat:     celery -A osbakery beat (optional cron jobs)
  redis:    redis:7
  db:       postgres:16
  minio:    minio (or skip if using real S3)
```

The `worker` image should include: `packer`, `salt-call`, `libguestfs-tools`, `qemu-user-static`, `xz-utils`, `kpartx`, `dosfstools`, `e2fsprogs`.

## Sizing

| Concurrent builds | RAM        | Disk          | CPU    |
| ----------------- | ---------- | ------------- | ------ |
| 1                 | 4 GB       | 20 GB scratch | 4 vCPU |
| 4                 | 12 GB      | 60 GB scratch | 8 vCPU |
| 16                | 32+ GB     | 200 GB scratch | 32 vCPU |

`xz` is the dominant CPU consumer; bandwidth to artifact storage is the dominant network consumer.

## Backups

- `postgres` — standard pg_dump cadence.
- `artifacts` — bucket-level versioning + lifecycle rules. Artifacts are reproducible so retention can be aggressive (e.g. 30 days).
- `packer/` and `salt/` — git, with a remote.

## Observability

The `LOGGING` config sends `osbakery`, `builds`, and `django` to stdout in a structured-ish format. Pipe stdout to your log aggregator (CloudWatch / Loki / Vector). Worker logs are the noisiest — set log level to `INFO` in production.
