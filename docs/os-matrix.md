# OS catalog & provisioning matrix

How os-bakery **sources** each OS's base image and how it **provisions** (bakes)
it. Generated from `catalog/upstream/*`, `catalog/management/commands/seed_catalog.py`,
`recipes/.../seed_recipes.py`, `builds/orchestrator.py`, and `builds/provisioners/*`.
URLs below are a snapshot — the live list lives in the `UpstreamImage` rows
(auto-polled for the four OS with a watcher, manually seeded for the rest).

## How sourcing works

- **Watchers** (`catalog/upstream/`) poll an upstream index and emit releases /
  per-target image URLs. Registered (auto-polled): **batocera, ubuntu, raspios,
  haos**. All other OS are **seeded manually** in `seed_catalog.py` (their
  changelog/source page is in `CHANGELOG_URLS`).
- The orchestrator fetches the `source_url`, caches/mirrors it (S3
  `os-bakery-artifacts`), then runs the provisioner against a working copy.

## How provisioning is dispatched (`builds/orchestrator.py:_mount_and_provision`)

1. `os_slug == proxmox-ve` → `proxmox_autoinstall`
2. `os_slug == batocera` → `batocera_pkg`
3. `os_slug == haos` → `haos_pkg`
4. else by `recipe.provisioner.slug`: **`salt`** (default) → `local_salt`;
   **`cloud-init`** → `cloud_init`; `ansible` → not implemented.

Only one shipped recipe is `cloud-init` (`ubuntu-desktop`); everything else
defaults to `salt`. ESPHome is built by the dedicated `worker-esphome` (firmware
compile, not an image bake).

## Summary

| OS | upstream source (auto?) | image type | provisioner | salt runs | rootfs autoresize on burn |
|----|-------------------------|------------|-------------|-----------|---------------------------|
| batocera | updates.batocera.org (✓) | `.img.gz` (squashfs+SHARE) | `batocera_pkg` | **bake** | SHARE self-expands first boot |
| raspios | downloads.raspberrypi.com (✓) | `.img.xz` (ext4) | `local_salt` (salt) | **bake** | `init_resize` (cmdline.txt) |
| ubuntu | cloud-images / cdimage / releases (✓) | `.img`/`.qcow2` (cloud), `.iso`/`+raspi.img.xz` | `local_salt`; desktop = `cloud_init` | **bake** (cloud/server), first-boot (desktop) | cloud-init `growpart` |
| debian | cloud.debian.org / raspi.debian.net / beagle (manual) | `.qcow2`/`.img.xz` | `local_salt` | **bake** | cloud-init `growpart` / `init_resize` |
| kali | cdimage.kali.org / kali.download (manual) | `.iso` (amd64), `.img.xz` (rpi) | `local_salt` (rpi img) | **bake** | cloud-init / raspi resize |
| haos | github.com/home-assistant/operating-system (✓) | `.img.xz` (appliance) | `haos_pkg` | n/a (Supervisor) | HAOS data partition grows |
| proxmox-ve | download.proxmox.com (manual) | `.iso` (installer) | `proxmox_autoinstall` | first boot | installer formats target |
| popos | iso.pop-os.org (manual) | `.iso` (installer) | `cloud_init`/installer | first boot | installer |
| omarchy | omarchy.org (manual) | `.iso` (installer) | (installer) | first boot | installer |
| l4t (jetson) | developer.nvidia.com (manual) | `.zip` SD image | `local_salt` | **bake** | resize |
| esphome | github.com/esphome/esphome (✓ manual) | `.bin` firmware | `worker-esphome` (compile) | n/a | n/a |
| windows | microsoft.com (placeholder) | download page | — (not baked) | n/a | n/a |
| macos | apple.com (placeholder) | download page | — (not baked) | n/a | n/a |

## Per-OS detail

### batocera  (watcher: `catalog/upstream/batocera.py`, index `https://batocera.org/changelog`)
- **URLs:** per-device `.img.gz` on `updates.batocera.org`, e.g.
  `https://updates.batocera.org/anbernic-rgxx3/stable/last/batocera-rk3568-anbernic-rgxx3-42-20251016.img.gz`;
  x86_64 via a Katapult CDN. Targets: rg353p/rg353v(+extras), rg552, flip-2,
  pocket-5, ayn-odin-2, pc-amd64 `[full]`/`[zen]`.
- **Provisioning** (`batocera_pkg.py`): buildroot, no apt/chroot-exec. Grow SHARE,
  chroot the squashfs root, **`pacman -U` the `misc-salt` package** (from
  `SALT_PACKAGE_URLS`, host-side download), write `pillar/batocera.sls`, then
  `salt-call --local state.apply batocera` → `state.highstate`, then
  `batocera-services enable`. The package owns the state tree + minion conf.
- **Scripts:** `misc-salt` `pacman/batoexec` + `salt-init-minion`/`salt-init-pillar`
  (in `batocera-utils`); os-bakery side curates grains (`batocera_resolution`/
  `usb_devices` SIGILL under qemu) and strips NUL from logged output.

### raspios  (watcher: `catalog/upstream/raspios.py`, index `https://downloads.raspberrypi.com/raspios_lite_arm64/images/`)
- **URLs:** `…/raspios_lite_arm64/images/raspios_lite_arm64-<date>/<date>-raspios-<codename>-arm64-lite.img.xz`
  (and `raspios_arm64` for desktop). Targets rpi3/4/5, variants `lite`/`desktop`.
- **Provisioning** (`local_salt.py`, `salt`): loop-mount, grow rootfs, chroot,
  add SaltProject apt repo + `apt-get install salt-minion`, `salt-call --local
  state.apply` at bake. Honours fstab `/boot` vs `/boot/firmware`.
- **Scripts:** `local_salt._CHROOT_SALT_SCRIPT`.

### ubuntu  (watcher: `catalog/upstream/ubuntu.py`, index `https://cloud-images.ubuntu.com/releases/`)
- **URLs:** cloud/server `https://cloud-images.ubuntu.com/releases/<ver>/release/ubuntu-<ver>-server-cloudimg-{amd64,arm64}.img`;
  rpi `https://cdimage.ubuntu.com/releases/<ver>/release/ubuntu-<ver>-preinstalled-{server,desktop}-arm64+raspi.img.xz`;
  desktop `.iso` on `releases.ubuntu.com`.
- **Provisioning:** server/cloud/rpi → `local_salt` (bake-time salt, same as
  raspios). **`ubuntu-desktop` → `cloud_init`** (first-boot salt).
- **Scripts:** `local_salt._CHROOT_SALT_SCRIPT`; or `cloud_init` NoCloud user-data.

### debian  (manual seed)
- **URLs:** cloud `https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-{amd64,arm64}.qcow2`;
  rpi `https://raspi.debian.net/tested-images/trixie/raspi_{4,5}_trixie.img.xz`;
  beaglebone `https://files.beagle.cc/.../am335x-debian-12.x-…-armhf-…img.xz`.
- **Provisioning:** `local_salt` (bake). Scripts: `_CHROOT_SALT_SCRIPT`.

### kali  (manual seed)
- **URLs:** installer `https://cdimage.kali.org/kali-<ver>/kali-linux-<ver>-installer-amd64.iso`;
  rpi `https://kali.download/arm-images/kali-<ver>/kali-linux-<ver>-raspberry-pi-arm64.img.xz`.
- **Provisioning:** rpi `.img` → `local_salt` (bake); installer `.iso` → installer/first-boot.

### haos  (watcher: `catalog/upstream/haos.py`, GitHub releases API)
- **URLs:** `https://github.com/home-assistant/operating-system/releases/download/<ver>/haos_<board>-<ver>.img.xz`
  (ha-green/yellow, odroid-*, generic-x86-64, rpi…).
- **Provisioning** (`haos_pkg.py`): Supervisor appliance — inject first-boot
  network/SSH onto the boot partition + a baked add-on backup; **no chroot salt**.

### proxmox-ve  (manual seed)
- **URLs:** `https://download.proxmox.com/iso/proxmox-ve_<ver>-1.iso`.
- **Provisioning** (`proxmox_autoinstall.py`): rebuild the installer ISO with an
  unattended `answer.toml`; salt runs on first boot.

### pop!\_os / omarchy  (manual seed, installer ISOs)
- **URLs:** `https://iso.pop-os.org/22.04/amd64/{intel,nvidia}/pop-os_22.04_…iso`;
  `https://omarchy.org/releases/omarchy-2.0.0-x86_64.iso`.
- **Provisioning:** installer-based / `cloud_init` first-boot; not chroot-baked.

### l4t (NVIDIA Jetson)  (manual seed)
- **URLs:** `https://developer.nvidia.com/.../jp_<ver>_…sd_card_image_jetson-*.zip`
  (jetson-nano / xavier-nx / orin-nano).
- **Provisioning:** `local_salt` against the unzipped SD image.

### esphome  (manual seed)
- **URLs:** `https://github.com/esphome/esphome/releases/download/<ver>/esphome-<ver>-factory-<chip>.bin`.
- **Provisioning:** `worker-esphome` compiles firmware from the device YAML —
  not an OS image bake.

### windows / macos  (placeholders)
- `source_url` points at the vendor download page (`microsoft.com`, `apple.com`);
  these are catalog entries for fleet/role taxonomy, not baked by os-bakery.

## Provisioner backends — scripts reference

| backend | file | what it runs |
|---------|------|--------------|
| `local_salt` | `builds/provisioners/local_salt.py` | loop-mount, grow (+4 GiB) `growpart`+`resize2fs`, chroot, `_CHROOT_SALT_SCRIPT` (add SaltProject apt repo+key → `apt-get install salt-minion` → `salt-call --local state.apply`). Stages states from `SALT_STATES_ROOT`. Preserves cloud-init `growpart` / raspios `init_resize`. |
| `batocera_pkg` | `builds/provisioners/batocera_pkg.py` | grow SHARE, chroot squashfs, host-side download + `pacman -U misc-salt` (`SALT_PACKAGE_URLS`), write `pillar/batocera.sls`, `state.apply batocera` → `state.highstate`, `batocera-services enable`. Grain curation + NUL-strip. |
| `cloud_init` | `builds/provisioners/cloud_init.py` | bake a NoCloud seed: `write_files` `/srv/salt` (+top) + `/srv/pillar` + masterless `/etc/salt/minion`; `runcmd` `bootstrap-salt.sh` → `salt-call --local state.highstate` on first boot. |
| `proxmox_autoinstall` | `builds/provisioners/proxmox_autoinstall.py` | repack the PVE installer ISO with `answer.toml`; first-boot `salt-call --local state.highstate`. |
| `haos_pkg` | `builds/provisioners/haos_pkg.py` | boot-partition first-boot config (network/SSH) + baked Supervisor backup. |
| `packer_arm_tools` | `builds/provisioners/packer_arm_tools.py` | legacy: master-connected `salt-minion` baked via the packer-builder-arm chroot. |

## Salt-at-bake vs first-boot, and autoresize

- **Bake-time** (`local_salt`, `batocera_pkg`): salt is installed and states are
  applied inside a (qemu) chroot during the build; the image ships fully
  provisioned. Both grow the image to fit the install but **do not** disable the
  OS's first-boot rootfs/SHARE expand, so flashing to a larger card still fills
  it (raspios `init_resize`, Ubuntu/Debian cloud-init `growpart`, batocera SHARE).
- **First-boot** (`cloud_init`, `proxmox_autoinstall`): salt runs on the device
  on first boot via the injected seed/answer file.
