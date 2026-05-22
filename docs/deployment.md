# Deployment

## Local stack via compose

`compose.yaml` at the repo root brings up everything needed to bake
images end-to-end:

| Service       | Purpose                                                                              |
| ------------- | ------------------------------------------------------------------------------------ |
| `postgres`    | Django state (catalog, recipes, builds, tenants, …).                                 |
| `redis`       | Celery broker + result backend.                                                      |
| `minio`       | S3-compatible artifact store. Single-node, console at `:9001`.                       |
| `minio-init`  | One-shot that creates the `os-bakery-artifacts` bucket on first boot.                |
| `salt-master` | Idle by default — baked images can point their minion config at this for fleet join. |
| `web`         | `python manage.py runserver` on `:8000`. Auto-migrates + seeds catalog + recipes on first boot. |
| `worker`      | `celery -A osbakery worker -Q builds,default --concurrency 2`. Includes the build toolchain (qemu-utils, kpartx, xz, parted, docker.io). |

### One-command bring-up

```sh
make compose-up           # docker compose up -d --build
make compose-logs         # tail web + worker logs
make compose-shell        # python manage.py shell against the stack
make compose-down         # stop (keep volumes)
make compose-reset        # stop AND wipe volumes (fresh DB / S3 / Salt pki)
```

After `compose-up`:

- Web UI — <http://localhost:8000/>
- Admin — <http://localhost:8000/admin/> (no superuser by default; create one with
  `docker compose exec web python manage.py createsuperuser`)
- MinIO console — <http://localhost:9001/> (osbakery / osbakery-secret)
- Salt master ZeroMQ ports — `localhost:4505` (pub) + `localhost:4506` (ret)
- Postgres — `localhost:5432` (only reachable from other compose services
  by default; uncomment the `ports:` mapping in compose.yaml to expose)

The web container mounts the repo at `/app` so edits hot-reload via the
StatReloader.

### Env wiring

Service-to-env mapping lives in `compose.yaml` as an x-anchor (`x-django-env`)
shared by `web` and `worker`. To override locally, drop a
`compose.override.yaml` next to `compose.yaml`:

```yaml
services:
  web:
    environment:
      DJANGO_DEBUG: "false"
      PACKER_ARM_TOOLS_ENABLED: "true"
```

### Notes / gotchas

- **First-boot warm-up** — `web` runs `migrate + seed_catalog + seed_recipes`
  before `runserver`. Allow ~15 s after `compose up` before the first GET.
- **Salt-master volume mounts** — the cdalvaro image expects state + pillar
  trees under `/home/salt/data/srv/{salt,pillar}` (not `/srv`). The bind
  mounts are read-only; ownership warnings on startup are cosmetic.
- **packer-arm-tools** — disabled by default. Set
  `PACKER_ARM_TOOLS_ENABLED=true` on the worker once the
  `cznewt/packer-arm-tools:latest` image is pulled (the worker mounts
  the host Docker socket — set `/var/run/docker.sock` in an override).
- **Postgres password** — `osbakery / osbakery`. Don't reuse outside the
  dev box.

## Production — separate processes

The compose stack is dev-grade (single-node MinIO, autoreload runserver,
auto-accept Salt keys). For production:

| Component     | Production swap                                                       |
| ------------- | --------------------------------------------------------------------- |
| `web`         | `gunicorn osbakery.wsgi` (the `web` target in `Dockerfile` already serves this) behind nginx for TLS + static.|
| `worker`      | Same image, drop the `--check` loop, run with `--max-tasks-per-child=10`. |
| `redis`       | Managed Redis (AWS ElastiCache, Memorystore, …) with TLS + auth.       |
| `postgres`    | Managed Postgres (RDS, Cloud SQL, …) — `pg_dump` cadence for backups. |
| `minio`       | Real S3 (AWS / Wasabi / Cloudflare R2) — set `ARTIFACT_STORAGE_BACKEND=s3` + real bucket / endpoint / keys. |
| `salt-master` | Per the fleet's existing salt-master deployment (see `models/newt-sites-model/component/salt/`). os-bakery doesn't need its own. |
| `celery beat` | Add this once upstream version-watch + token expiry cleanup land.     |

The **Celery worker is special** — it needs root or sudo-without-password
access to `losetup`, `mount`, `umount`, `kpartx`, `xz`, `qemu-img`. Run it
on a *dedicated build host* with the worker target's image:

```sh
docker run -d --restart=always \
    --privileged \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v /srv/os-bakery:/srv/os-bakery \
    --env-file /etc/os-bakery/worker.env \
    --name os-bakery-worker \
    ghcr.io/cznewt/os-bakery:worker
```

`--privileged` is needed for loop-device + kpartx; `/var/run/docker.sock`
lets the worker shell out to packer-arm-tools.

## Required env

See `.env.example` for the full list. Compose sets these for you;
production needs them in `worker.env` / `web.env`:

```
DJANGO_SECRET_KEY=<random>
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

PACKER_ARM_TOOLS_ENABLED=true
SALT_MASTER_URL=salt-master.internal
```

## Sizing

| Concurrent builds | RAM        | Disk          | CPU    |
| ----------------- | ---------- | ------------- | ------ |
| 1                 | 4 GB       | 20 GB scratch | 4 vCPU |
| 4                 | 12 GB      | 60 GB scratch | 8 vCPU |
| 16                | 32+ GB     | 200 GB scratch | 32 vCPU |

`xz` is the dominant CPU consumer; bandwidth to artifact storage is the
dominant network consumer.

## Backups

- `postgres` — `pg_dump` cadence (state is recoverable from seeds + git
  but tenant data isn't).
- `artifacts` bucket — versioning + 30-day lifecycle rules. Artifacts are
  reproducible, so aggressive retention is fine.
- `packer/` and `salt/` — git, with a remote.

## Observability

The `LOGGING` config sends `osbakery`, `builds`, and `django` to stdout
in a structured-ish format. Pipe stdout to your log aggregator (CloudWatch
/ Loki / Vector). Worker logs are the noisiest — set log level to `INFO`
in production.
