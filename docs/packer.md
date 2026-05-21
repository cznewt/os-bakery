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

See `docs/catalog.md` for the full HardwareTarget × variant matrix these
templates feed.

| OS         | Template                                          | HardwareTarget    | Variants          |
| ---------- | ------------------------------------------------- | ----------------- | ----------------- |
| Batocera   | `packer/batocera/rpi3/template.pkr.hcl`           | `rpi3`            | —                 |
| Batocera   | `packer/batocera/rpi4/template.pkr.hcl`           | `rpi4`            | —                 |
| Batocera   | `packer/batocera/rpi5/template.pkr.hcl`           | `rpi5`            | —                 |
| Batocera   | `packer/batocera/pc-amd64/template.pkr.hcl`       | `pc-amd64`        | —                 |
| RaspiOS    | `packer/raspios/rpi3/template.pkr.hcl`            | `rpi3`            | `lite`, `desktop` |
| RaspiOS    | `packer/raspios/rpi4/template.pkr.hcl`            | `rpi4`            | `lite`, `desktop` |
| RaspiOS    | `packer/raspios/rpi5/template.pkr.hcl`            | `rpi5`            | `lite`, `desktop` |
| Ubuntu     | `packer/ubuntu/rpi4/template.pkr.hcl`             | `rpi4`            | `server`, `desktop` |
| Ubuntu     | `packer/ubuntu/rpi5/template.pkr.hcl`             | `rpi5`            | `server`, `desktop` |
| Ubuntu     | `packer/ubuntu/generic-arm64/template.pkr.hcl`    | `generic-arm64`   | `server`          |
| Ubuntu     | `packer/ubuntu/pc-amd64/template.pkr.hcl`         | `pc-amd64`        | `server`, `desktop` |
| Ubuntu     | `packer/ubuntu/vm-qemu/template.pkr.hcl`          | `vm-qemu`         | `server`          |
| Ubuntu     | `packer/ubuntu/vm-hyperv/template.pkr.hcl`        | `vm-hyperv`       | `server`          |
| Ubuntu     | `packer/ubuntu/vm-virtualbox/template.pkr.hcl`    | `vm-virtualbox`   | `server`          |
| HAOS       | `packer/haos/rpi4/template.pkr.hcl`               | `rpi4`            | —                 |
| HAOS       | `packer/haos/rpi5/template.pkr.hcl`               | `rpi5`            | —                 |
| HAOS       | `packer/haos/pc-amd64/template.pkr.hcl`           | `pc-amd64`        | —                 |

Templates whose **Variants** column lists multiple values accept a
`variant` Packer variable. Directory names always match the HardwareTarget
slug from `docs/catalog.md`.

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

## Related: existing ARM build tooling (packer-arm-tools)

The user already maintains an Argo Workflows action that builds per-device
ARM images using the `mkaczanowski/packer-builder-arm` plugin —
`/home/newt/work/models/service-catalog/cicd-tools/packer-arm-tools/`.

It differs from os-bakery's current scaffold in two important ways:

1. **One Packer run does both refresh and customization.** The `arm` builder
   loop-mounts the image, copies `qemu-aarch64-static` into the chroot, and
   runs shell provisioners (`config_raspios.sh`, `config_batocera.sh`,
   `install_salt.sh`) inside it. os-bakery's templates currently use the
   `null` builder and only refresh the cached mirror — provisioning is
   deferred to `builds.orchestrator._mount_and_provision`, which is still a
   no-op.
2. **Customization is bash, not Salt.** packer-arm-tools writes
   `/etc/hostname`, `/etc/wpa_supplicant/wpa_supplicant.conf`,
   `/etc/salt/minion.d/minion.conf` directly. os-bakery's plan is to do the
   same work through Salt states with pillar values driven by
   `RecipeOption.option_values`.

When wiring the real `_mount_and_provision`, the two reasonable paths are
either (a) shell out to a packer-arm-tools-style chroot + `salt-call --local`
inside it, or (b) treat packer-arm-tools as the canonical ARM build path
and have os-bakery only orchestrate / track / serve its outputs. See the
`reference-packer-arm-tools` memory for the preset list and naming
convention.
