# Packer guide

Packer keeps the *base image cache* fresh. It is **not** the per-user customization step — that's Salt. Treat Packer like a build cache.

## When Packer runs

| Trigger                          | Effect                                                            |
| -------------------------------- | ----------------------------------------------------------------- |
| `packer build template.pkr.hcl` on a host with disk space | Refreshes one `UpstreamImage` mirror.   |
| `cron` job on the build host     | Daily / weekly refresh of all templates.                          |
| Admin clicks "refresh" in Django | (Future) Triggers Celery → Packer subprocess.                     |

## Template anatomy

Every template:

1. Declares a `null` source builder (we're not booting a VM, just shelling).
2. Sets locals for the upstream URL, the work-dir path, and the cache-dir path.
3. Runs one `provisioner "shell-local"` that calls helpers from `packer/shared/_lib.sh`:
   - `fetch URL OUT [SHA]` — `curl` with sha256 verification.
   - `extract ARCHIVE OUT` — gunzip / xz / unzip into a raw image.
   - `pack_xz RAW OUT` — repackage as `.img.xz`.
   - `write_manifest PATH SRC_URL IMG_PATH` — drops a JSON sidecar.

The manifest is the contract with Django. `manage.py sync_filesystem` reads these manifests and updates the corresponding `UpstreamImage` rows.

```jsonc
// packer cache: ~/.cache/os-bakery/batocera/rpi5/manifest.json
{
  "source_url": "https://updates.batocera.org/.../batocera-bcm2712-41-stable.img.gz",
  "local_path": "/home/.../batocera-41-rpi5.img.xz",
  "size_bytes": 1234567890,
  "sha256": "abc123...",
  "built_at": "2026-05-20T12:34:56Z"
}
```

## Templates currently shipped

| OS         | Template                                  | Hardware target    |
| ---------- | ----------------------------------------- | ------------------ |
| Batocera   | `packer/batocera/rpi5/template.pkr.hcl`   | `rpi5`             |
| Batocera   | `packer/batocera/rpi4/template.pkr.hcl`   | `rpi4`             |
| Batocera   | `packer/batocera/x86_64/template.pkr.hcl` | `pc-x86_64-uefi`   |
| Raspios    | `packer/raspios/rpi5/template.pkr.hcl`    | `rpi5`             |
| Raspios    | `packer/raspios/rpi4/template.pkr.hcl`    | `rpi4`             |
| Raspios    | `packer/raspios/rpi-zero2w/template.pkr.hcl` | `rpi-zero2w`    |
| Ubuntu     | `packer/ubuntu/arm64/template.pkr.hcl`    | `rpi5` / `rpi4` (preinstalled-server-arm64) |
| Ubuntu     | `packer/ubuntu/amd64/template.pkr.hcl`    | `pc-x86_64-uefi`   |

To add a new target: copy the closest template, fix the URL + cache path, and add a row to the [Adding a new hardware target](operations.md#adding-a-new-hardware-target) checklist.

## Hooks for "core" bake-in

Variables `core_salt_states` and `core_salt_pillar` (declared in `packer/shared/variables.pkr.hcl`) are intended for the case where you want *every* image built on top of a base to share certain settings. The current templates don't apply them yet — they're hooks for a future `salt-call`-against-mounted-image provisioner step in `shared/_lib.sh`.

## Running

```sh
cd packer/batocera/rpi5
packer init .
packer validate -var-file=../../shared/dev.pkrvars.hcl template.pkr.hcl
packer build    -var-file=../../shared/dev.pkrvars.hcl template.pkr.hcl
```

After a successful run:

```sh
python manage.py sync_filesystem
```

That reconciles `infra.PackerTemplate` (so admins see "last run" times) and points `catalog.UpstreamImage.local_path` at the freshly-baked file.

## Common gotchas

- **`xz` is slow.** It dominates wall-clock time. Use `xz -T0` (already in `_lib.sh`) to use all cores.
- **Disk space.** A Raspberry Pi OS Lite base image is ~600MB; the same expanded for a recipe build is ~3GB. Each Celery worker needs ~10GB free to be safe.
- **ARM cross-customization.** When the Salt step is added to Packer (not just to the per-build orchestrator), running ARM binaries on an x86 host needs `qemu-user-static` + `binfmt_misc`.
