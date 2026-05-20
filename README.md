# os-bakery

Build and distribute customized OS images — Batocera, Raspberry Pi OS, Ubuntu, … — for ARM and x86 targets. Base images are kept fresh by **Packer**; per-end-user customizations are baked in with **Salt**; everything is orchestrated and tracked by a small **Django** application.

## What it does

```
upstream image  ──Packer──▶  cached base image  ──Salt──▶  customized artifact  ──download token──▶  end user
                                  (catalog.UpstreamImage)        (builds.Artifact)        (builds.DownloadToken)
```

- **Catalog** — what we can build (architectures, hardware targets, OSes, releases, upstream images).
- **Recipes** — how we customize a base image for a given end user.
- **Builds** — a build queue + artifact store with time-bounded download tokens.
- **Infra** — registry that points the app at the on-disk Packer templates and Salt formulas.

## Quick start

```sh
cp .env.example .env
make dev
make migrate
make superuser
make run             # Django on :8000
make celery          # Celery worker for builds (needs Redis)
```

## Repository layout

```
.
├── osbakery/                 # Django project (settings, celery, urls)
├── catalog/                  # Architectures, OSes, releases, upstream images
├── recipes/                  # Customer-facing customization profiles
├── builds/                   # Build orchestration + artifacts + downloads
├── infra/                    # Packer/Salt registry + sync_filesystem command
├── packer/                   # HCL templates that refresh base images
├── salt/                     # States + pillars baked into images
├── docs/                     # Architecture, data model, workflows, ops
└── storage/                  # Local artifact + work directories (gitignored)
```

See [`docs/README.md`](docs/README.md) for the full guide.
