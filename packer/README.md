# Packer templates

Packer is used here for one job: **keep the local cache of base OS images fresh and reproducible**.

The application's per-user customizations are applied later by Salt (see `salt/`). Packer's role is:

1. Pull the latest upstream image (Batocera / Raspberry Pi OS / Ubuntu).
2. Optionally pre-bake "core" customizations that *every* image built on top should share (kernel modules, default user, SSH key, hardening).
3. Stamp it with metadata (checksum, build time, source URL).
4. Drop it into the local image cache where the Django app's `UpstreamImage` records point.

## Layout

```
packer/
├── shared/                 # shared variables, locals, manifest snippets
│   ├── variables.pkr.hcl
│   └── manifest.pkr.hcl
├── batocera/
│   ├── rpi5/template.pkr.hcl
│   ├── rpi4/template.pkr.hcl
│   └── x86_64/template.pkr.hcl
├── raspios/
│   ├── rpi5/template.pkr.hcl
│   ├── rpi4/template.pkr.hcl
│   └── rpi-zero2w/template.pkr.hcl
└── ubuntu/
    ├── arm64/template.pkr.hcl
    └── amd64/template.pkr.hcl
```

## Conventions

- Every template uses the `null` source builder and drives `shell-local` provisioners. These templates manipulate disk images on the host — they do not spin up VMs for the build itself.
- Every template writes a `manifest.json` next to its output. The Django command `python manage.py sync_filesystem` reconciles those manifests with `catalog.UpstreamImage`.
- Variables for cache location, upstream URLs, and checksums live in `shared/variables.pkr.hcl`. Override them with `-var-file=`.

## Running

```sh
cd packer/batocera/rpi5
packer init .
packer build -var-file=../../shared/dev.pkrvars.hcl template.pkr.hcl
```

The `Makefile` at the repo root has a `packer-%` target that wraps this.
