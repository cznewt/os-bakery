# Supported devices and platforms

A wider-angle view than `catalog.md`. The catalog is what we currently ship
ready-made `UpstreamImage` rows for; this page also covers platforms the
companion tooling (`packer-arm-tools`) supports today even though we haven't
seeded them into the catalog yet, plus aspirational targets we'd want to
add next.

## At a glance

| Category                      | Examples                                          | In catalog?                  |
| ----------------------------- | ------------------------------------------------- | ---------------------------- |
| ARM single-board computers    | Raspberry Pi 3 / 4 / 5                            | ✓                            |
| ARM SBCs (specialty)          | BeagleBone Black / Blue, NVIDIA Jetson Nano       | ✓ (armhf / arm64)            |
| Generic ARM64 servers / SBCs  | Pine64, Rock Pi, Ampere cloud                     | ✓ (`generic-arm64`)          |
| x86\_64 PCs                   | Laptops, mini-PCs, NUC-class                      | ✓ (`pc-amd64`)               |
| Curated desktop distros       | Omarchy (Arch + Hyprland), Pop!_OS (Intel/NVIDIA) | ✓                            |
| Virtual machines              | QEMU/KVM, Hyper-V, VirtualBox                     | ✓                            |
| Hypervisor (planned)          | VMware ESXi, Proxmox cluster                      | aspirational                 |

## ARM single-board computers

### Raspberry Pi 3 / 4 / 5

| Pi     | SoC      | RAM     | OS images we publish                                                 |
| ------ | -------- | ------- | -------------------------------------------------------------------- |
| `rpi3` | BCM2837  | 1 GB    | Batocera, RaspiOS (lite / desktop)                                   |
| `rpi4` | BCM2711  | 1–8 GB  | Batocera, RaspiOS (lite / desktop), Ubuntu (server / desktop), HAOS |
| `rpi5` | BCM2712  | 4 / 8 / 16 GB | Batocera, RaspiOS (lite / desktop), Ubuntu (server / desktop), HAOS |

All three boot via the Pi firmware (`boot_method=rpi`); arm64 only. Pi Zero
2 W is supported in the same image family as `rpi3` (BCM2710/BCM2837
class) but we don't currently surface it as a separate HardwareTarget.

### BeagleBone Black + Blue

TI AM335x Cortex-A8, single core, armhf 32-bit. Both boards share the
SoC; Blue adds onboard IMU, barometer, and motor drivers for robotics.
Catalog rows:

- HardwareTarget `beaglebone-black` (armhf, `uboot`).
- HardwareTarget `beaglebone-blue` (armhf, `uboot`).
- OperatingSystem `debian` release `12` Bookworm — sourced from
  `https://rcn-ee.com/rootfs/bb.org/`.

The same image flashes to both boards; differences (sensor drivers,
device-tree overlays) are applied per recipe via Salt or chroot scripts.
`packer-arm-tools` ships compatible presets:

- `beaglebone-black-debian-server-arm32.json`
- `beaglebone-black-debian-server-salt-minion-arm32.json`

### NVIDIA Jetson family

arm64 with NVIDIA's "Linux for Tegra" (L4T) kernel — not interchangeable
with stock arm64 distros. Each Tegra family is stuck on a different L4T
major because the kernel is family-specific:

| HardwareTarget       | SoC           | L4T release in catalog | Notes                                  |
| -------------------- | ------------- | ---------------------- | -------------------------------------- |
| `jetson-nano`        | Tegra X1      | `r32.7.6`              | EOL — last release that supports X1.   |
| `jetson-xavier-nx`   | Tegra Xavier  | `r35.6.0`              | Lower-power Xavier module + dev kit.   |
| `jetson-orin-nano`   | Tegra Orin    | `r36.4.0`              | Current flagship dev kit (4 / 8 GB).   |

OperatingSystem `l4t`. SD card images from
`https://developer.nvidia.com/embedded/jetson-linux`. `packer-arm-tools`
preset (`jetson-nano-l4t-server-arm64.json`) currently targets the Nano;
Orin / Xavier presets are a follow-up.

Future expansion: Jetson AGX Orin, Jetson Orin NX, Jetson AGX Xavier
(same OS, new HardwareTarget rows; each ships its own SD card image URL).

### Generic ARM64 SBCs

Pine64, Rock Pi 4 / 5, Orange Pi, Banana Pi, Ampere Altra dev kits, and any
other arm64 board that boots via UEFI. We collapse these into one
HardwareTarget — `generic-arm64` — and let the recipe apply per-board
device-tree / firmware overlays. Today only Ubuntu Server arm64 is
seeded; Debian + Armbian images can be added with a single
UpstreamImage row each.

## x86\_64 / PCs

### Generic UEFI

The `pc-amd64` HardwareTarget covers the common case:
- Laptops (any vendor with UEFI firmware)
- Mini-PCs (Intel NUC, ASUS PN-series, Beelink, Minisforum, …)
- Workstation desktops

OSes currently seeded for `pc-amd64`:
- Batocera (single image)
- Ubuntu (`server` + `desktop`)
- HAOS (generic-x86-64)

### BIOS / legacy

Old PCs still booting via legacy BIOS. The catalog doesn't currently split
BIOS from UEFI; if you need BIOS-only images, add a `pc-amd64-bios`
HardwareTarget with `boot_method=bios` and point recipes at it.

## Virtual machines

| Slug              | Hypervisor                  | Boot   | Notes                                                                  |
| ----------------- | --------------------------- | ------ | ---------------------------------------------------------------------- |
| `vm-qemu`         | QEMU / KVM                  | uefi   | Also covers Proxmox VE (KVM under the hood); cloud-image friendly.     |
| `vm-hyperv`       | Microsoft Hyper-V (Gen2)    | uefi   | Convert `.img` → `.vhdx` (`qemu-img convert -O vhdx`) at deploy time. |
| `vm-virtualbox`   | Oracle VirtualBox           | bios   | Convert `.img` → `.ova` or `.vdi` via `VBoxManage import`.            |

Today only Ubuntu Server is published for VM targets — desktop-in-VM is
left to users who'd rather flash the desktop ISO themselves.

### Future hypervisor targets

- **VMware ESXi / Workstation** — would be `vm-vmware` (`.vmdk` output).
- **Proxmox VE templates** — currently covered by `vm-qemu`, but a
  dedicated slug could expose Proxmox-native `.tar.gz` LXC templates if
  we ever bake containers, not just VMs.
- **AWS / GCP / Azure cloud images** — `cloud-aws`, `cloud-gcp`,
  `cloud-azure` slugs would each map to a cloud-specific publish step
  (AMI registration, GCE image import, Azure Managed Image upload).

## Curated desktop distros

### Omarchy

DHH/Basecamp's curated Arch + Hyprland desktop opinion-set. amd64 only.
Catalog row: OperatingSystem `omarchy`, current release `2.0`. The
upstream artifact is a single live ISO — recipes for Omarchy mostly
amount to picking it as a base and dropping in a different keymap or
shell config; Hyprland customizations layer on top at first boot.

### Pop!_OS

System76's Ubuntu-based desktop. Catalog row: OperatingSystem `popos`,
release `22.04` (Jammy-based; 24.04 in alpha at time of writing).
Variants:

- `intel` — stock kernel, Intel/AMD GPU.
- `nvidia` — NVIDIA proprietary driver baked in.

Both ISOs are amd64; arm64 Pi builds exist as developer previews but
aren't in the catalog yet.

## Kali Linux

OffSec's Debian-based pentest / red-team distro. Quarterly cadence —
catalog pinned to the current series. Targets:

- `pc-amd64` (desktop) — `cdimage.kali.org/.../kali-linux-{rel}-installer-amd64.iso`
- `rpi4` / `rpi5` — `kali.download/arm-images/.../kali-linux-{rel}-raspberry-pi-arm64.img.xz`
  (a single arm64+raspi image runs on both Pi tiers).

## Proxmox VE

Proxmox Server Solutions GmbH's bare-metal Debian-based KVM + LXC
hypervisor. amd64 only. Catalog row: OperatingSystem `proxmox-ve` at
release `8.3`. Single artifact: the installer ISO at
`download.proxmox.com/iso/proxmox-ve_{rel}-1.iso`. Recipes for Proxmox
mostly amount to preseeding the network + cluster join answers in the
installer.

## Specialty / future

- **Armbian** — generic arm64 / armhf SBC distro; would slot under
  `generic-arm64` or per-board HardwareTargets.
- **Alpine Linux** — embedded use cases; HAOS-style appliance pattern
  applies (small read-only RootFS).
- **OpenWrt** — router / network appliance images; would need a separate
  pipeline because OpenWrt artifacts are kernel + initramfs rather than
  whole-disk images.
- **postmarketOS / mobile Linux** — phones, tablets, handhelds. Pattern
  fits arm64 SBC but each device is its own HardwareTarget.

## OS × hardware support matrix

`rpi*` = Raspberry Pi 3/4/5, `bb-*` = BeagleBone Black/Blue,
`jetson-*` = NVIDIA Jetson Nano / Xavier NX / Orin Nano,
`vm-*` = QEMU/Hyper-V/VirtualBox.

| OS           | rpi3 | rpi4 | rpi5 | pc-amd64 | generic-arm64 | vm-* | bb-* | jetson-nano | jetson-xavier-nx | jetson-orin-nano |
| ------------ | :--: | :--: | :--: | :------: | :-----------: | :--: | :--: | :---------: | :--------------: | :--------------: |
| Batocera     | ✓   | ✓   | ✓   | ✓       | —             | —   | —   | —           | —                | —                |
| Ubuntu       | —    | ✓   | ✓   | ✓       | ✓ (server)   | ✓¹ | —   | —           | —                | —                |
| Debian       | —    | ✓   | ✓   | ✓       | ✓ (server)   | ✓¹ | ✓ (Bookworm armhf) | — | —              | —                |
| RaspiOS      | ✓   | ✓   | ✓   | —        | —             | —   | —   | —           | —                | —                |
| HAOS         | —    | ✓   | ✓   | ✓       | —             | —   | —   | —           | —                | —                |
| Omarchy      | —    | —    | —    | ✓ (desktop)   | —        | —   | —   | —           | —                | —                |
| Pop!_OS      | —    | —    | —    | ✓ (intel+nvidia) | —    | —   | —   | —           | —                | —                |
| L4T          | —    | —    | —    | —        | —             | —   | —   | ✓ r32.7    | ✓ r35.6         | ✓ r36.4         |
| Kali         | —    | ✓   | ✓   | ✓       | —             | —   | —   | —           | —                | —                |
| Proxmox VE   | —    | —    | —    | ✓ (ISO)        | —       | —   | —   | —           | —                | —                |

¹ VM targets are server-only; desktop-in-VM is the user installing the
desktop ISO themselves.

## Adding a new platform

1. **Reuse an existing HardwareTarget** if you can — most new boards fit
   `generic-arm64`. Pick a slug only if recipes need to disambiguate
   firmware, overlays, or boot flow.
2. Add to `Architecture` if a new arch is involved (armhf is the most
   likely re-addition; `riscv` is already in the enum).
3. Drop a new HardwareTarget row into the seed (`catalog/management/commands/seed_catalog.py`).
4. Add `UpstreamImage` rows for every (OS, target, variant) combo you
   want to publish. The seed file is the source of truth — update there
   and run `make seed-catalog`.
5. Add a Packer template under `packer/<os>/<target>/template.pkr.hcl` if
   the existing templates don't cover the URL pattern.
6. If the platform needs chroot-style customization (i.e. it's ARM and
   you want to bake hostname / Wi-Fi / salt-minion at build time), add a
   `packer-arm-tools` preset row to
   `builds/provisioners/packer_arm_tools.py:PRESETS`.
7. Document the platform here.
