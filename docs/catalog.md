# Catalog matrix

The catalog answers two questions: **what can we bake?** and **what does the
output run on?** This page enumerates every row the `seed_catalog` management
command creates, plus the variant / hardware combinations we publish images
for.

Run `python manage.py seed_catalog` (or `make seed-catalog`) to populate a
fresh database with the rows below. The command is idempotent — it uses
`get_or_create` so it's safe to re-run after upstream releases bump.

## Architectures (2)

| slug      | family | bits | name                  |
| --------- | ------ | ---- | --------------------- |
| `arm64`   | arm    | 64   | ARM 64-bit (aarch64)  |
| `amd64`   | x86    | 64   | x86 64-bit            |

`armhf` (32-bit) is intentionally omitted — every supported Pi (3/4/5) now
ships 64-bit RaspiOS / Batocera images, and we don't need a 32-bit toolchain
for end-user devices.

## Hardware targets (8)

| slug             | arch    | boot | name                                | typical use                                |
| ---------------- | ------- | ---- | ----------------------------------- | ------------------------------------------ |
| `rpi3`           | arm64   | rpi  | Raspberry Pi 3 (BCM2837)            | Pi 3 B / 3B+ / 3A+                         |
| `rpi4`           | arm64   | rpi  | Raspberry Pi 4 (BCM2711)            | Pi 4 / Pi 400                              |
| `rpi5`           | arm64   | rpi  | Raspberry Pi 5 (BCM2712)            | Pi 5                                       |
| `pc-amd64`       | amd64   | uefi | Generic x86\_64 PC (UEFI)           | laptops, mini PCs, NUC-class               |
| `generic-arm64`  | arm64   | uefi | Generic ARM64 server                | cloud VMs, Ampere, Rock Pi, Pine64         |
| `vm-qemu`        | amd64   | uefi | QEMU / KVM virtual machine          | dev VMs, Proxmox                           |
| `vm-hyperv`      | amd64   | uefi | Microsoft Hyper-V Gen2              | Windows hosts, Azure Stack HCI             |
| `vm-virtualbox`  | amd64   | bios | Oracle VirtualBox                   | desktop sandbox                            |

## Operating systems (4)

| slug       | kind     | vendor               | notes                                          |
| ---------- | -------- | -------------------- | ---------------------------------------------- |
| `batocera` | retro    | Batocera community   | Read-only `/boot` + `/userdata`; per-Pi build. |
| `ubuntu`   | server   | Canonical            | Desktop / server / cloud variants per release. |
| `raspios`  | desktop  | Raspberry Pi Ltd.    | One arm64 image, three Pi tiers consume it.    |
| `haos`     | iot      | Home Assistant       | Immutable container OS; **not Salt-friendly**. |

`OperatingSystem.kind` carries the dominant flavor; the per-variant
desktop/server split lives in `UpstreamImage.variant`.

## Releases (initial seeds)

The seed command marks one release per OS as `is_default` so recipes that
don't pin a release resolve there. Bump these as upstream cuts new versions.

| OS         | version       | channel | codename   | default? |
| ---------- | ------------- | ------- | ---------- | -------- |
| `batocera` | `41`          | stable  |            | yes      |
| `ubuntu`   | `24.04`       | lts     | `Noble`    | yes      |
| `raspios`  | `2025-05-13`  | stable  | `Bookworm` | yes      |
| `haos`     | `14.2`        | stable  |            | yes      |

## Upstream image matrix (23 rows)

### Batocera 41 (4 rows, no variant)

| target     | variant | source URL                                                                                |
| ---------- | ------- | ----------------------------------------------------------------------------------------- |
| `rpi3`     | (none)  | `https://updates.batocera.org/bcm2710/stable/last/batocera-bcm2710-41-stable.img.gz` †    |
| `rpi4`     | (none)  | `https://updates.batocera.org/bcm2711/stable/last/batocera-bcm2711-41-stable.img.gz`      |
| `rpi5`     | (none)  | `https://updates.batocera.org/bcm2712/stable/last/batocera-bcm2712-41-stable.img.gz`      |
| `pc-amd64` | (none)  | `https://updates.batocera.org/x86_64/stable/last/batocera-x86_64-41-stable.img.gz`        |

† Batocera dropped active rpi3 builds at some point — verify the URL still
returns a current image before relying on it. Keep the row so the schema
holds; mark it inactive in admin if upstream is gone.

### Ubuntu 24.04 LTS (10 rows)

The cloud-image is the canonical raw `.img` for amd64/arm64 server use; the
RPi-targeted images are Canonical's `preinstalled-{server,desktop}-arm64+raspi`
builds; desktop amd64 is a live-installer ISO.

| target          | variant   | source URL                                                                                                       |
| --------------- | --------- | ---------------------------------------------------------------------------------------------------------------- |
| `generic-arm64` | `server`  | `https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-arm64.img`                  |
| `rpi4`          | `server`  | `https://cdimage.ubuntu.com/releases/24.04/release/ubuntu-24.04-preinstalled-server-arm64+raspi.img.xz`          |
| `rpi4`          | `desktop` | `https://cdimage.ubuntu.com/releases/24.04/release/ubuntu-24.04-preinstalled-desktop-arm64+raspi.img.xz`         |
| `rpi5`          | `server`  | `https://cdimage.ubuntu.com/releases/24.04/release/ubuntu-24.04-preinstalled-server-arm64+raspi.img.xz`          |
| `rpi5`          | `desktop` | `https://cdimage.ubuntu.com/releases/24.04/release/ubuntu-24.04-preinstalled-desktop-arm64+raspi.img.xz`         |
| `pc-amd64`      | `server`  | `https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img`                  |
| `pc-amd64`      | `desktop` | `https://releases.ubuntu.com/24.04/ubuntu-24.04.1-desktop-amd64.iso`                                             |
| `vm-qemu`       | `server`  | `https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img`                  |
| `vm-hyperv`     | `server`  | `https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img` ‡                |
| `vm-virtualbox` | `server`  | `https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img` ‡                |

‡ The VM rows reuse the amd64 cloud-image; format conversion (qcow2 → vhdx /
ova) is a Packer post-processor concern, not an upstream URL change. We
intentionally don't ship `desktop` variants for VM targets — desktop-in-VM is
the user installing the desktop ISO themselves.

### Raspberry Pi OS 2025-05-13 Bookworm (6 rows)

RaspiOS publishes a single arm64 image file per variant — the same `.img.xz`
flashes onto rpi3 / rpi4 / rpi5, with per-board firmware/overlays loaded at
boot. We expose three `HardwareTarget` rows anyway so recipes can target a
specific Pi (apply different overlays, force a specific Wi-Fi country, etc.).

| target | variant   | source URL                                                                                                                                 |
| ------ | --------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `rpi3` | `desktop` | `https://downloads.raspberrypi.com/raspios_arm64/images/raspios_arm64-2025-05-13/2025-05-13-raspios-bookworm-arm64.img.xz`                  |
| `rpi3` | `lite`    | `https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2025-05-13/2025-05-13-raspios-bookworm-arm64-lite.img.xz`   |
| `rpi4` | `desktop` | (same desktop URL as rpi3)                                                                                                                 |
| `rpi4` | `lite`    | (same lite URL as rpi3)                                                                                                                    |
| `rpi5` | `desktop` | (same desktop URL as rpi3)                                                                                                                 |
| `rpi5` | `lite`    | (same lite URL as rpi3)                                                                                                                    |

`variant=lite` is the headless / server-oriented build. The user's mental
model of "desktop/server" maps to `variant in {desktop, lite}`.

### Home Assistant OS 14.2 (3 rows, no variant)

HAOS ships per-target images on GitHub Releases. There are no desktop/server
variants — HAOS is a single-purpose appliance OS.

| target     | variant | source URL                                                                                                       |
| ---------- | ------- | ---------------------------------------------------------------------------------------------------------------- |
| `rpi4`     | (none)  | `https://github.com/home-assistant/operating-system/releases/download/14.2/haos_rpi4-64-14.2.img.xz`             |
| `rpi5`     | (none)  | `https://github.com/home-assistant/operating-system/releases/download/14.2/haos_rpi5-64-14.2.img.xz`             |
| `pc-amd64` | (none)  | `https://github.com/home-assistant/operating-system/releases/download/14.2/haos_generic-x86-64-14.2.img.xz`      |

## HAOS caveat: it doesn't speak Salt

Home Assistant OS is a hardened, container-only OS. There's no apt, no Python,
and no Salt minion can run on it. Customizations that work at bake time:

- pre-populate `CONFIG/network/my-network` (Wi-Fi creds, static IP) on the
  config partition;
- inject `authorized_keys` for the SSH add-on;
- drop a `homeassistant/configuration.yaml` snippet on the data partition.

Anything else (themes, integrations, automations) ships with the user's
HA snapshot, restored at first boot. The os-bakery Salt states for HAOS
(`salt/states/haos/*`) document the few file-injection things that *are*
possible and stop there — the per-build orchestrator skips `salt-call` for
HAOS recipes and only runs the inject step.

## Alignment with existing packer-arm-tools

The user already maintains an Argo action — packer-arm-tools at
`/home/newt/work/models/service-catalog/cicd-tools/packer-arm-tools/` — that
bakes per-device ARM images using `mkaczanowski/packer-builder-arm` (chroot
+ qemu-aarch64-static). Its image presets follow the naming pattern:

```
<device-family>-<os>-<variant>[-salt-minion]-<arch>.json
```

…e.g. `raspberry-pi-34-raspios-server-salt-minion-arm64.json`. The
shipped presets cover RaspiOS (server / desktop, arm32 / arm64),
Ubuntu Server arm64 for Pi, Batocera arm64 for Pi 4, Beaglebone
debian-armhf, and Jetson Nano L4T.

The matrix above is shaped to be **compatible** with those presets — every
`(target, variant)` row here has a corresponding preset in packer-arm-tools
(or a clear gap we know about, e.g. HAOS, the VM targets, x86 batocera).
The two systems can coexist by either: (a) having os-bakery's
`_mount_and_provision` shell out to packer-arm-tools for ARM targets, or
(b) re-implementing the same chroot pattern in os-bakery's orchestrator.
See `docs/packer.md` and the `reference-packer-arm-tools` memory for the
detailed comparison.

## How this maps to fleet ingestion

Once a baked image boots, its salt-minion (if present) registers with the
fleet master. The minion `id` follows the convention
`<owner>-<location>-<role>-<instance>` (see the salt-roles memory). The
role slug recipes write into the minion config decides which states the
master then applies:

| Role slug    | What the master applies                          |
| ------------ | ------------------------------------------------ |
| `pve`        | `linux`, `salt`, `zerotier`                      |
| `kube`       | `linux`, `salt`, `crio`, `kubernetes`, `zerotier`|
| `docker`     | `linux`, `salt`, `docker`                        |
| `runner`     | `linux`, `salt`, `docker`                        |
| `batocera`   | `batocera`, `alloy`, `salt`                      |

os-bakery doesn't ship these state bodies — they live in the user's fleet
Salt formula repos. os-bakery only bakes in the minion config that lets the
fleet master pick up the right ones.
