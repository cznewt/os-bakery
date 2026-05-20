# Architecture

## Components

```
┌────────────────────────────────────────────────────────────────────────┐
│                              os-bakery                                  │
│                                                                         │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│   │  Django web  │    │ Celery worker│    │ Packer (CLI) │             │
│   │  (gunicorn)  │    │  (builds q.) │    │  cron/manual │             │
│   └──────┬───────┘    └──────┬───────┘    └──────┬───────┘             │
│          │                   │                   │                      │
│          ▼                   ▼                   ▼                      │
│   ┌───────────────────────────────────────────────────────────────┐    │
│   │                 PostgreSQL  +  Redis broker                    │    │
│   └───────────────────────────────────────────────────────────────┘    │
│          │                   │                                          │
│          ▼                   ▼                                          │
│   ┌──────────────┐    ┌────────────────────────────────────────┐       │
│   │ Static files │    │      Artifact storage (FS or S3)        │       │
│   │ (whitenoise) │    └────────────────────────────────────────┘       │
│   └──────────────┘                                                       │
└────────────────────────────────────────────────────────────────────────┘
```

## Django apps

| App        | Responsibility                                                |
| ---------- | ------------------------------------------------------------- |
| `catalog`  | Inventory of architectures, hardware targets, OSes, releases, upstream images. |
| `recipes`  | Customer-facing customization profiles, versioned, with parameter forms. |
| `builds`   | Build queue, orchestrator, artifacts, download tokens.        |
| `infra`    | DB-side registry of on-disk Packer templates and Salt formulas. |
| `osbakery` | Project root: settings, celery, top-level urls.               |

Why this split:

- `catalog` is read-mostly metadata. It changes when a new RPi board is supported or a new Ubuntu LTS lands.
- `recipes` is where operators iterate. Versioned snapshots keep older builds reproducible.
- `builds` is the only app that talks to the filesystem at runtime. Containing the side effects to one app makes everything else easier to test.
- `infra` exists so the admin UI can show "what's wired up" without operators having to `ssh` to the build host.

## Request flow: creating a build

1. **Submit.** The frontend or API client posts to `POST /api/builds/` with `{ recipe_slug, hardware_target_slug, option_values }`.
2. **Validate.** `BuildRequestSerializer.create` resolves the recipe → current `RecipeVersion`, the OS default release, and the `UpstreamImage` row for the chosen hardware target.
3. **Persist.** A `BuildRequest` row is created with status `queued`.
4. **Dispatch.** `builds.signals.enqueue_new_build_requests` (post_save on `BuildRequest`) calls `builds.tasks.run_build.apply_async(queue="builds")` and stores the Celery task id.
5. **Bake.** A worker picks it up, transitions through `preparing → building → finalizing → succeeded`, and writes `BuildEvent` rows along the way.
6. **Publish.** The orchestrator drops the packed image into `storages["artifacts"]`, creates an `Artifact` row, and issues a `DownloadToken`.
7. **Deliver.** The user (or the API) is told the download URL: `/d/<token>/`.

## Storage

Two storage backends are used:

| Backend     | Configured at                            | Used for                  |
| ----------- | ---------------------------------------- | ------------------------- |
| `default`   | local filesystem                         | Django uploads (icons, …) |
| `artifacts` | local FS (dev) or S3-compatible (prod)   | Image artifacts           |

Use `ARTIFACT_STORAGE_BACKEND=s3` in `.env` to flip artifact storage to an S3-compatible bucket (the [`storages.backends.s3.S3Storage`](https://django-storages.readthedocs.io/) backend ships with `django-storages`).

## Deployment topology (typical)

```
[ users ] ── HTTPS ──▶ [ nginx ] ── [ gunicorn (Django) ] ──┐
                                                            ├─▶ [ PostgreSQL ]
                                                            ├─▶ [ Redis (broker) ]
                                                            └─▶ [ S3 / minio ]
                       [ celery worker (builds q.) ] ───────┘
                       [ celery beat (optional) ]
                       [ packer host with KVM/loopback ]
```

The Celery worker that runs builds needs root + `losetup` / `kpartx` (or libguestfs `guestmount`) + `xz` + `qemu-utils`. It is normally a *dedicated build host*, not the web tier.
