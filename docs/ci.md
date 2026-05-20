# CI

Three GitHub Actions workflows live under `.github/workflows/`:

| File                  | Trigger                                  | What it does                                                          |
| --------------------- | ---------------------------------------- | --------------------------------------------------------------------- |
| `ci.yml`              | PRs + push to `main`                     | ruff lint + format, `manage.py check`, `pytest`, `packer validate`, Salt YAML sanity, build container images (PR only, no push). |
| `docker.yml`          | push to `main` + tags `v*` + manual      | Build & push `web` and `worker` container images to GHCR.             |
| `refresh-images.yml`  | weekly schedule + manual                 | Run Packer to refresh OS base images and upload the manifests.        |

## `ci.yml` — pull-request gate

Five jobs, all run in parallel:

1. **`lint`** — `ruff check .` and `ruff format --check .` on Python 3.12.
2. **`test`** — `pytest` against an in-memory SQLite. Migrations are skipped (`--no-migrations` in `pyproject.toml`) so a brand-new checkout still works without `makemigrations`.
3. **`packer-validate`** — installs Packer 1.11.2 and runs `packer init` + `packer validate` on every `packer/*/*/template.pkr.hcl`. This catches HCL syntax errors and missing variables without touching upstream image URLs.
4. **`salt-syntax`** — strips Jinja blocks from each `.sls` and parses the rest as YAML. Cheap smoke test for grammar drift.
5. **`django-image`** — runs only on PRs; builds both `web` and `worker` container targets via Buildx with GHA cache, no push. The push side lives in `docker.yml`.

## `docker.yml` — container image build

Triggers on push to `main`, on tags `v*`, and via `workflow_dispatch`. Builds the two Dockerfile targets in parallel and pushes to GHCR:

- `ghcr.io/<owner>/<repo>-web`
- `ghcr.io/<owner>/<repo>-worker`

Tags applied by `docker/metadata-action`:

| When                | Tag(s)                              |
| ------------------- | ----------------------------------- |
| push to `main`      | `main`, `sha-<short>`, `latest`     |
| tag `v1.2.3`        | `1.2.3`, `1.2`, `sha-<short>`       |
| manual dispatch     | `sha-<short>`                       |

The workflow needs `packages: write` on `GITHUB_TOKEN` — already declared.

To pull:

```sh
docker pull ghcr.io/cznewt/os-bakery-web:main
docker pull ghcr.io/cznewt/os-bakery-worker:main
```

## `refresh-images.yml` — OS base image build

Runs the actual Packer templates. By default the weekly cron only refreshes the three Raspberry Pi OS variants — Batocera and Ubuntu images are too big for hosted runners without aggressive free-disk hacks.

Manual usage:

```
gh workflow run refresh-images.yml \
   -f target=batocera/rpi5 \
   -f runner=bakery-build
```

Inputs:

- `target` — single template path (e.g. `batocera/rpi5`). Empty = default matrix.
- `runner` — `ubuntu-latest` (default) or `bakery-build` for a self-hosted runner with disk + KVM.

Outputs:

- `manifest-<target>` — the JSON sidecar `_lib.sh::write_manifest` writes (one per template). Always uploaded.
- `image-<target>` — the actual `*.img.xz`. Only uploaded when the workflow env `UPLOAD_IMAGES=true` is set (default off because >2 GB artifacts get awkward fast). Wire this to an S3 bucket via a step you add in your fork.

### Self-hosted runners for the heavy stuff

For Batocera, Ubuntu, or anything Salt-baked, attach a runner with:

- 50+ GB disk
- 8 GB+ RAM
- `xz`, `qemu-img`, `unzip`, `kpartx`, `libguestfs-tools`, `qemu-user-static`, `binfmt-support`
- Labelled `bakery-build` (or change the workflow input default)

Then dispatch with `runner=bakery-build`. The job skips the "free disk space" hack on self-hosted runners.

## Local equivalents

Everything CI does is reproducible locally:

```sh
make lint
make test
( cd packer/raspios/rpi5 && packer init . && packer validate template.pkr.hcl )
docker build --target web -t os-bakery-web .
docker build --target worker -t os-bakery-worker .
```

The container builds use the same Buildx cache scope on the runner — there's no CI-only build step.
