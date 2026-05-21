"""Seed the catalog with the supported OS / hardware / release / image matrix.

Documented in ``docs/catalog.md``. Idempotent — every row uses
``get_or_create`` so running it again after upstream version bumps just adds
the new releases / images without disturbing the existing ones.

Usage:

    python manage.py seed_catalog
    python manage.py seed_catalog --quiet
"""

from __future__ import annotations

from typing import NamedTuple

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import (
    Architecture,
    HardwareTarget,
    OperatingSystem,
    OSRelease,
    UpstreamImage,
)


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


class ArchSeed(NamedTuple):
    slug: str
    name: str
    family: str
    bits: int


class TargetSeed(NamedTuple):
    slug: str
    name: str
    architecture: str  # arch slug
    boot_method: str
    soc: str = ""
    notes: str = ""


class OSSeed(NamedTuple):
    slug: str
    name: str
    vendor: str
    kind: str
    homepage: str = ""
    license: str = ""
    summary: str = ""


class ReleaseSeed(NamedTuple):
    os_slug: str
    version: str
    channel: str
    codename: str = ""
    is_default: bool = False


class ImageSeed(NamedTuple):
    os_slug: str
    release_version: str
    release_channel: str
    target_slug: str
    variant: str
    source_url: str
    format: str  # UpstreamImage.Format value


ARCHITECTURES: list[ArchSeed] = [
    ArchSeed("arm64", "ARM 64-bit (aarch64)", "arm", 64),
    ArchSeed("armhf", "ARM 32-bit hard-float (armv7l)", "arm", 32),
    ArchSeed("amd64", "x86 64-bit (x86_64)", "x86", 64),
]

HARDWARE_TARGETS: list[TargetSeed] = [
    TargetSeed("rpi3", "Raspberry Pi 3", "arm64", "rpi", soc="BCM2837",
               notes="Pi 3 B / 3B+ / 3A+. arm64-capable."),
    TargetSeed("rpi4", "Raspberry Pi 4", "arm64", "rpi", soc="BCM2711",
               notes="Pi 4 (1-8 GB) and Pi 400."),
    TargetSeed("rpi5", "Raspberry Pi 5", "arm64", "rpi", soc="BCM2712",
               notes="Pi 5."),
    TargetSeed("pc-amd64", "Generic x86_64 PC (UEFI)", "amd64", "uefi",
               notes="Laptops, mini PCs, NUC-class."),
    TargetSeed("generic-arm64", "Generic ARM64 server", "arm64", "uefi",
               notes="Cloud VMs, Ampere, generic non-Pi SBCs."),
    TargetSeed("vm-qemu", "QEMU / KVM virtual machine", "amd64", "uefi"),
    TargetSeed("vm-hyperv", "Microsoft Hyper-V Gen2", "amd64", "uefi"),
    TargetSeed("vm-virtualbox", "Oracle VirtualBox", "amd64", "bios"),
    TargetSeed("beaglebone-black", "BeagleBone Black", "armhf", "uboot",
               soc="TI AM335x",
               notes="1 GHz Cortex-A8. Boots from eMMC / SD. armhf only."),
    TargetSeed("beaglebone-blue", "BeagleBone Blue", "armhf", "uboot",
               soc="TI AM335x",
               notes="Robotics-focused BeagleBone Black variant — adds IMU, "
                     "barometer, motor drivers."),
    TargetSeed("jetson-nano", "NVIDIA Jetson Nano", "arm64", "uboot",
               soc="Tegra X1",
               notes="L4T (Linux for Tegra) only — the Tegra kernel is "
                     "Ubuntu-based but not interchangeable with stock arm64. "
                     "Last supported L4T: r32.7.x."),
    TargetSeed("jetson-xavier-nx", "NVIDIA Jetson Xavier NX", "arm64", "uboot",
               soc="Tegra Xavier",
               notes="L4T r35.x. Lower-power Xavier module for the dev kit."),
    TargetSeed("jetson-orin-nano", "NVIDIA Jetson Orin Nano", "arm64", "uboot",
               soc="Tegra Orin",
               notes="Current Jetson dev kit (8 GB / 4 GB). L4T r36.x."),
    # ---- Retro handhelds (Batocera per-device builds) -----------------
    TargetSeed("rg552", "Anbernic RG552", "arm64", "uboot",
               soc="Rockchip RK3399",
               notes="Dual-screen Anbernic flagship handheld."),
    TargetSeed("rg353p", "Anbernic RG353P", "arm64", "uboot",
               soc="Rockchip RK3566",
               notes="RG353 series — clamshell, plastic shell."),
    TargetSeed("rg353ps", "Anbernic RG353PS", "arm64", "uboot",
               soc="Rockchip RK3566",
               notes="RG353 series — clamshell, slim variant."),
    TargetSeed("rg353v", "Anbernic RG353V", "arm64", "uboot",
               soc="Rockchip RK3566",
               notes="RG353 series — vertical layout (Game Boy style)."),
    TargetSeed("rg353vs", "Anbernic RG353VS", "arm64", "uboot",
               soc="Rockchip RK3566",
               notes="RG353 series — vertical, slim variant."),
    TargetSeed("rg503", "Anbernic RG503", "arm64", "uboot",
               soc="Rockchip RK3566",
               notes="OLED handheld."),
    TargetSeed("loki-zero", "Anbernic Loki Zero", "arm64", "uboot",
               notes="Loki-series budget handheld (per Batocera download page)."),
    TargetSeed("flip-2", "Anbernic Flip 2", "arm64", "uboot",
               notes="Clamshell flip-style handheld (per Batocera download page)."),
    TargetSeed("pocket-5", "Retroid Pocket 5", "arm64", "uboot",
               notes="Retroid Pocket 5 handheld (per Batocera download page)."),
]

OPERATING_SYSTEMS: list[OSSeed] = [
    OSSeed("batocera", "Batocera.linux", "Batocera community", "retro",
           homepage="https://batocera.org",
           summary="Read-only retro-gaming OS with per-Pi builds."),
    OSSeed("ubuntu", "Ubuntu", "Canonical", "server",
           homepage="https://ubuntu.com",
           summary="General-purpose Linux; desktop / server / cloud variants."),
    OSSeed("debian", "Debian GNU/Linux", "Debian Project", "server",
           homepage="https://www.debian.org",
           summary="Upstream of Ubuntu and RaspiOS; long-lived stable releases."),
    OSSeed("raspios", "Raspberry Pi OS", "Raspberry Pi Ltd.", "desktop",
           homepage="https://www.raspberrypi.com/software/",
           summary="Debian-based OS for the Raspberry Pi family."),
    OSSeed("haos", "Home Assistant OS", "Open Home Foundation", "iot",
           homepage="https://www.home-assistant.io/installation/",
           summary="Immutable container OS for the Home Assistant stack."),
    OSSeed("omarchy", "Omarchy", "Basecamp / DHH", "desktop",
           homepage="https://omarchy.org",
           summary="Curated Arch + Hyprland desktop opinion-set. amd64 only."),
    OSSeed("popos", "Pop!_OS", "System76", "desktop",
           homepage="https://pop.system76.com",
           summary="Ubuntu-based desktop; Intel / Nvidia hardware-tailored ISOs."),
    OSSeed("l4t", "Linux for Tegra", "NVIDIA", "embedded",
           homepage="https://developer.nvidia.com/embedded/jetson-linux",
           summary="Ubuntu-based OS with NVIDIA's Tegra kernel — Jetson SoCs."),
    OSSeed("kali", "Kali Linux", "OffSec", "desktop",
           homepage="https://www.kali.org",
           summary="Debian-based pentesting / red-team distribution; "
                   "amd64 ISO + arm64 Raspberry Pi images."),
    OSSeed("proxmox-ve", "Proxmox Virtual Environment", "Proxmox Server Solutions GmbH",
           "server",
           homepage="https://www.proxmox.com/en/proxmox-virtual-environment",
           summary="Bare-metal Debian-based KVM + LXC hypervisor "
                   "(`proxmox-ve_*.iso`). amd64 only."),
]

RELEASES: list[ReleaseSeed] = [
    # Batocera — keep the last two supported annual releases. 41 dropped
    # once 43 became stable; older builds still work but receive no fixes.
    ReleaseSeed("batocera", "42", "stable"),
    ReleaseSeed("batocera", "43", "stable", is_default=True),
    # Ubuntu — Jammy (22.04) is still in standard support until 2027; Noble
    # (24.04) is the headline LTS for new builds. 16.04 Xenial dropped (ESM
    # only, end-of-mainstream-support).
    ReleaseSeed("ubuntu", "22.04", "lts", codename="Jammy"),
    ReleaseSeed("ubuntu", "24.04", "lts", codename="Noble", is_default=True),
    # Debian — Trixie (13) is current stable; Bookworm (12) kept for the
    # BeagleBone armhf builds (rcn-ee.com still ships Bookworm-based images).
    ReleaseSeed("debian", "12", "stable", codename="Bookworm"),
    ReleaseSeed("debian", "13", "stable", codename="Trixie", is_default=True),
    # RaspiOS — date-stamped releases. Keep a recent history so recipes
    # can pin to a specific image while new builds default to the latest.
    ReleaseSeed("raspios", "2023-05-03", "stable", codename="Bullseye"),
    ReleaseSeed("raspios", "2024-07-04", "stable", codename="Bookworm"),
    ReleaseSeed("raspios", "2024-11-19", "stable", codename="Bookworm"),
    ReleaseSeed("raspios", "2025-03-15", "stable", codename="Bookworm"),
    ReleaseSeed("raspios", "2025-05-13", "stable", codename="Bookworm",
                is_default=True),
    # Home Assistant OS — only the current major is supported.
    ReleaseSeed("haos", "17.1", "stable", is_default=True),
    # Curated desktop distros.
    ReleaseSeed("omarchy", "2.0", "stable", is_default=True),
    ReleaseSeed("popos", "22.04", "lts", codename="Jammy", is_default=True),
    # Linux for Tegra — one release per Tegra family. r36 is the headline
    # (Orin), but Jetson Nano + Xavier are stuck on older majors.
    ReleaseSeed("l4t", "r32.7.6", "stable"),  # Jetson Nano (Tegra X1)
    ReleaseSeed("l4t", "r35.6.0", "stable"),  # Jetson Xavier NX
    ReleaseSeed("l4t", "r36.4.0", "stable", is_default=True),  # Jetson Orin
    # Kali Linux — quarterly cadence; keep the last four quarters seeded.
    ReleaseSeed("kali", "2024.4", "stable"),
    ReleaseSeed("kali", "2025.1", "stable"),
    ReleaseSeed("kali", "2025.2", "stable"),
    ReleaseSeed("kali", "2025.3", "stable", is_default=True),
    # Proxmox VE — 9.x is the current major; 8.3 kept for legacy clusters.
    ReleaseSeed("proxmox-ve", "8.3", "stable"),
    ReleaseSeed("proxmox-ve", "9.1", "stable", is_default=True),
]


# --- URL templates (kept inline so the seed file is the one source of truth)

_BATOCERA = "https://updates.batocera.org/{platform}/stable/last/batocera-{platform}-{version}-stable.img.gz"

# Ubuntu — URL patterns are uniform across modern LTS releases; the only
# moving parts are the version number and the desktop-ISO point version.
_UBUNTU_RPI = "https://cdimage.ubuntu.com/releases/{release}/release/ubuntu-{release}-preinstalled-{variant}-arm64+raspi.img.xz"
_UBUNTU_CLOUD_ARM = "https://cloud-images.ubuntu.com/releases/{release}/release/ubuntu-{release}-server-cloudimg-arm64.img"
_UBUNTU_CLOUD_AMD = "https://cloud-images.ubuntu.com/releases/{release}/release/ubuntu-{release}-server-cloudimg-amd64.img"
# Point releases of the desktop ISO bump independently — pin the last known
# good per LTS here.
_UBUNTU_DESKTOP_AMD = {
    "22.04": "https://releases.ubuntu.com/22.04/ubuntu-22.04.5-desktop-amd64.iso",
    "24.04": "https://releases.ubuntu.com/24.04/ubuntu-24.04.1-desktop-amd64.iso",
}

# Debian — `/latest/` always resolves to the current point release.
_DEBIAN_CLOUD_AMD = "https://cloud.debian.org/images/cloud/{codename}/latest/debian-{major}-genericcloud-amd64.qcow2"
_DEBIAN_CLOUD_ARM = "https://cloud.debian.org/images/cloud/{codename}/latest/debian-{major}-genericcloud-arm64.qcow2"
# raspi.debian.net publishes per-Pi tested images.
_DEBIAN_RPI = "https://raspi.debian.net/tested-images/{codename}/raspi_{pi}_{codename}.img.xz"
# rcn-ee.com publishes BeagleBone Debian armhf images. URL has a moving
# date stamp; this is the current pattern as of mid-2025.
_DEBIAN_BBONE = (
    "https://rcn-ee.com/rootfs/bb.org/release/2025-04-06/bookworm-iot-armhf/"
    "bone-debian-12.10-iot-armhf-2025-04-06-4gb.img.xz"
)

# Omarchy — release ISO on GitHub Releases. Pin the latest tag.
_OMARCHY_ISO = "https://omarchy.org/releases/omarchy-2.0.0-x86_64.iso"

# Pop!_OS — Intel and NVIDIA-tailored desktop ISOs per LTS.
_POPOS_INTEL = "https://iso.pop-os.org/22.04/amd64/intel/pop-os_22.04_amd64_intel_22.iso"
_POPOS_NVIDIA = "https://iso.pop-os.org/22.04/amd64/nvidia/pop-os_22.04_amd64_nvidia_22.iso"

# NVIDIA L4T — one zipped SD card image per (Tegra family, release).
_L4T_NANO = (
    "https://developer.nvidia.com/downloads/embedded/l4t/r32_release_v7.6/"
    "jp_4.6.6_b39_sd_card_image_jetson-nano.zip"
)
_L4T_XAVIER_NX = (
    "https://developer.nvidia.com/embedded/l4t/r35_release_v6.0/release/"
    "jp_5.1.6_b39_sd_card_image_jetson-xavier-nx.zip"
)
_L4T_ORIN_NANO = (
    "https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v4.0/"
    "release/jp_6.1_b113_sd_card_image_jetson-orin-nano-devkit.zip"
)

# Kali Linux — amd64 installer ISO + arm64+raspi image (shared rpi4 / rpi5).
_KALI_AMD = "https://cdimage.kali.org/kali-{release}/kali-linux-{release}-installer-amd64.iso"
_KALI_RPI = "https://kali.download/arm-images/kali-{release}/kali-linux-{release}-raspberry-pi-arm64.img.xz"

# Proxmox VE — single amd64 bare-metal installer ISO per point release.
_PROXMOX_VE = "https://download.proxmox.com/iso/proxmox-ve_{release}-1.iso"

# RaspiOS — date-stamped folder + matching filename. Codename is the
# Debian series (bullseye, bookworm, …) lowercased.
_RASPIOS_DESKTOP = (
    "https://downloads.raspberrypi.com/raspios_arm64/images/"
    "raspios_arm64-{date}/{date}-raspios-{codename}-arm64.img.xz"
)
_RASPIOS_LITE = (
    "https://downloads.raspberrypi.com/raspios_lite_arm64/images/"
    "raspios_lite_arm64-{date}/{date}-raspios-{codename}-arm64-lite.img.xz"
)

# HAOS is versioned per release; one URL template covers every (version,
# platform) combo.
_HAOS = (
    "https://github.com/home-assistant/operating-system/releases/download/"
    "{version}/haos_{platform}-{version}.img.xz"
)


def _images() -> list[ImageSeed]:
    rows: list[ImageSeed] = []

    # Batocera 42 / 43 — one image per target per version, no variant.
    # Platform name is whatever the Batocera updates.batocera.org URL uses
    # as the per-device folder name (typically SoC for SBCs, slug for
    # handhelds).
    batocera_targets = [
        # Single-board computers — platform = SoC family
        ("rpi3", "bcm2710"),
        ("rpi4", "bcm2711"),
        ("rpi5", "bcm2712"),
        ("pc-amd64", "x86_64"),
        # Retro handhelds — platform = device slug
        ("rg552", "rg552"),
        ("rg353p", "rg353p"),
        ("rg353ps", "rg353ps"),
        ("rg353v", "rg353v"),
        ("rg353vs", "rg353vs"),
        ("rg503", "rg503"),
        ("loki-zero", "loki-zero"),
        ("flip-2", "flip-2"),
        ("pocket-5", "pocket-5"),
    ]
    for version in ("42", "43"):
        for target, platform in batocera_targets:
            rows.append(ImageSeed(
                "batocera", version, "stable", target, "",
                _BATOCERA.format(platform=platform, version=version),
                "img.gz",
            ))

    # Ubuntu 22.04 (Jammy) + 24.04 (Noble) — same shape: raspi-preinstalled
    # for rpi4/5 × server/desktop, cloud for generic-arm64 + pc-amd64 server,
    # ISO for pc-amd64 desktop, cloud-image for VM targets.
    for release in ("22.04", "24.04"):
        rows.append(ImageSeed("ubuntu", release, "lts", "generic-arm64",
                              "server",
                              _UBUNTU_CLOUD_ARM.format(release=release),
                              "img"))
        for target in ("rpi4", "rpi5"):
            for variant in ("server", "desktop"):
                rows.append(ImageSeed(
                    "ubuntu", release, "lts", target, variant,
                    _UBUNTU_RPI.format(release=release, variant=variant),
                    "img.xz",
                ))
        rows.append(ImageSeed("ubuntu", release, "lts", "pc-amd64",
                              "server",
                              _UBUNTU_CLOUD_AMD.format(release=release),
                              "img"))
        rows.append(ImageSeed("ubuntu", release, "lts", "pc-amd64",
                              "desktop", _UBUNTU_DESKTOP_AMD[release], "iso"))
        for target in ("vm-qemu", "vm-hyperv", "vm-virtualbox"):
            rows.append(ImageSeed(
                "ubuntu", release, "lts", target, "server",
                _UBUNTU_CLOUD_AMD.format(release=release), "img",
            ))

    # Debian 13 Trixie — cloud images for generic-arm64 / pc-amd64 / VMs,
    # plus raspi.debian.net images for the Pi family.
    rows.append(ImageSeed("debian", "13", "stable", "generic-arm64", "server",
                          _DEBIAN_CLOUD_ARM.format(codename="trixie", major="13"),
                          "qcow2"))
    rows.append(ImageSeed("debian", "13", "stable", "pc-amd64", "server",
                          _DEBIAN_CLOUD_AMD.format(codename="trixie", major="13"),
                          "qcow2"))
    for target in ("vm-qemu", "vm-hyperv", "vm-virtualbox"):
        rows.append(ImageSeed("debian", "13", "stable", target, "server",
                              _DEBIAN_CLOUD_AMD.format(codename="trixie", major="13"),
                              "qcow2"))
    for target, pi in [("rpi4", "4"), ("rpi5", "5")]:
        rows.append(ImageSeed("debian", "13", "stable", target, "",
                              _DEBIAN_RPI.format(codename="trixie", pi=pi),
                              "img.xz"))

    # Debian 12 Bookworm — kept around for the BeagleBone armhf builds.
    for target in ("beaglebone-black", "beaglebone-blue"):
        rows.append(ImageSeed("debian", "12", "stable", target, "",
                              _DEBIAN_BBONE, "img.xz"))

    # Omarchy — single desktop image for pc-amd64.
    rows.append(ImageSeed("omarchy", "2.0", "stable", "pc-amd64", "desktop",
                          _OMARCHY_ISO, "iso"))

    # Pop!_OS — Intel + NVIDIA desktop variants on pc-amd64.
    rows.append(ImageSeed("popos", "22.04", "lts", "pc-amd64", "intel",
                          _POPOS_INTEL, "iso"))
    rows.append(ImageSeed("popos", "22.04", "lts", "pc-amd64", "nvidia",
                          _POPOS_NVIDIA, "iso"))

    # Linux for Tegra — one image per Tegra family.
    rows.append(ImageSeed("l4t", "r32.7.6", "stable", "jetson-nano", "",
                          _L4T_NANO, "img"))
    rows.append(ImageSeed("l4t", "r35.6.0", "stable", "jetson-xavier-nx", "",
                          _L4T_XAVIER_NX, "img"))
    rows.append(ImageSeed("l4t", "r36.4.0", "stable", "jetson-orin-nano", "",
                          _L4T_ORIN_NANO, "img"))

    # Kali Linux — amd64 desktop installer ISO + arm64+raspi image, per
    # quarterly release.
    for kali_release in ("2024.4", "2025.1", "2025.2", "2025.3"):
        rows.append(ImageSeed("kali", kali_release, "stable", "pc-amd64",
                              "desktop",
                              _KALI_AMD.format(release=kali_release), "iso"))
        for target in ("rpi4", "rpi5"):
            rows.append(ImageSeed("kali", kali_release, "stable", target, "",
                                  _KALI_RPI.format(release=kali_release),
                                  "img.xz"))

    # Proxmox VE — single amd64 bare-metal installer ISO per major.
    for pve_release in ("8.3", "9.1"):
        rows.append(ImageSeed("proxmox-ve", pve_release, "stable",
                              "pc-amd64", "",
                              _PROXMOX_VE.format(release=pve_release), "iso"))

    # RaspiOS — one image per arm64 variant per dated release; three Pi
    # targets share each image.
    raspios_dates = [
        ("2023-05-03", "bullseye"),
        ("2024-07-04", "bookworm"),
        ("2024-11-19", "bookworm"),
        ("2025-03-15", "bookworm"),
        ("2025-05-13", "bookworm"),
    ]
    for date, codename in raspios_dates:
        desktop_url = _RASPIOS_DESKTOP.format(date=date, codename=codename)
        lite_url = _RASPIOS_LITE.format(date=date, codename=codename)
        for target in ("rpi3", "rpi4", "rpi5"):
            rows.append(ImageSeed("raspios", date, "stable", target,
                                  "desktop", desktop_url, "img.xz"))
            rows.append(ImageSeed("raspios", date, "stable", target,
                                  "lite", lite_url, "img.xz"))

    # HAOS — per-target appliance image, no variant. Only the current
    # supported major is seeded; older majors (14/15/16) are EOL.
    haos_targets = [
        ("rpi4", "rpi4-64"),
        ("rpi5", "rpi5-64"),
        ("pc-amd64", "generic-x86-64"),
    ]
    for version in ("17.1",):
        for target, platform in haos_targets:
            rows.append(ImageSeed(
                "haos", version, "stable", target, "",
                _HAOS.format(version=version, platform=platform),
                "img.xz",
            ))

    return rows


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = "Seed the catalog with the supported OS / hardware / release / image matrix."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--quiet", action="store_true",
            help="Suppress per-row output (still prints the summary).",
        )
        parser.add_argument(
            "--prune", action="store_true",
            help=(
                "Delete OSReleases (cascading their UpstreamImages) and "
                "UpstreamImage rows that are no longer in the seed. Use "
                "after removing entries from RELEASES / _images() so the "
                "DB matches the seed exactly."
            ),
        )

    def handle(self, *args, quiet: bool = False, prune: bool = False, **options) -> None:
        report = {"arch": 0, "target": 0, "os": 0, "release": 0, "image": 0,
                  "arch+": 0, "target+": 0, "os+": 0, "release+": 0, "image+": 0}

        with transaction.atomic():
            arch_by_slug: dict[str, Architecture] = {}
            for seed in ARCHITECTURES:
                obj, created = Architecture.objects.get_or_create(
                    slug=seed.slug,
                    defaults=dict(name=seed.name, family=seed.family,
                                  bits=seed.bits),
                )
                arch_by_slug[seed.slug] = obj
                report["arch"] += 1
                report["arch+"] += int(created)
                if not quiet:
                    self._echo("Architecture", obj.slug, created)

            target_by_slug: dict[str, HardwareTarget] = {}
            for tseed in HARDWARE_TARGETS:
                obj, created = HardwareTarget.objects.get_or_create(
                    slug=tseed.slug,
                    defaults=dict(
                        name=tseed.name,
                        architecture=arch_by_slug[tseed.architecture],
                        boot_method=tseed.boot_method,
                        soc=tseed.soc,
                        notes=tseed.notes,
                    ),
                )
                target_by_slug[tseed.slug] = obj
                report["target"] += 1
                report["target+"] += int(created)
                if not quiet:
                    self._echo("HardwareTarget", obj.slug, created)

            os_by_slug: dict[str, OperatingSystem] = {}
            for oseed in OPERATING_SYSTEMS:
                obj, created = OperatingSystem.objects.get_or_create(
                    slug=oseed.slug,
                    defaults=dict(name=oseed.name, vendor=oseed.vendor,
                                  kind=oseed.kind, homepage=oseed.homepage,
                                  license=oseed.license, summary=oseed.summary),
                )
                os_by_slug[oseed.slug] = obj
                report["os"] += 1
                report["os+"] += int(created)
                if not quiet:
                    self._echo("OperatingSystem", obj.slug, created)

            release_key: dict[tuple[str, str, str], OSRelease] = {}
            for rseed in RELEASES:
                obj, created = OSRelease.objects.get_or_create(
                    operating_system=os_by_slug[rseed.os_slug],
                    version=rseed.version,
                    channel=rseed.channel,
                    defaults=dict(codename=rseed.codename,
                                  is_default=rseed.is_default),
                )
                release_key[(rseed.os_slug, rseed.version, rseed.channel)] = obj
                report["release"] += 1
                report["release+"] += int(created)
                if not quiet:
                    self._echo("OSRelease",
                               f"{rseed.os_slug}@{rseed.version}/{rseed.channel}",
                               created)

            # Re-assert is_default per OS — earlier seed runs may have set
            # a different release as default, so we clear and reapply.
            os_with_explicit_default = {
                rseed.os_slug for rseed in RELEASES if rseed.is_default
            }
            for os_slug in os_with_explicit_default:
                OSRelease.objects.filter(
                    operating_system=os_by_slug[os_slug],
                ).update(is_default=False)
            for rseed in RELEASES:
                if rseed.is_default:
                    release_key[(rseed.os_slug, rseed.version, rseed.channel)].is_default = True
                    release_key[(rseed.os_slug, rseed.version, rseed.channel)].save(
                        update_fields=["is_default"]
                    )

            for iseed in _images():
                release = release_key[(iseed.os_slug, iseed.release_version,
                                       iseed.release_channel)]
                obj, created = UpstreamImage.objects.get_or_create(
                    release=release,
                    hardware_target=target_by_slug[iseed.target_slug],
                    variant=iseed.variant,
                    defaults=dict(format=iseed.format,
                                  source_url=iseed.source_url),
                )
                report["image"] += 1
                report["image+"] += int(created)
                if not quiet:
                    self._echo(
                        "UpstreamImage",
                        f"{iseed.os_slug}@{iseed.release_version} "
                        f"{iseed.target_slug} {iseed.variant or '(none)'}",
                        created,
                    )

        pruned = {"release": 0, "image": 0}
        if prune:
            seed_release_keys = {
                (r.os_slug, r.version, r.channel) for r in RELEASES
            }
            seed_image_keys = {
                (i.os_slug, i.release_version, i.release_channel,
                 i.target_slug, i.variant) for i in _images()
            }
            with transaction.atomic():
                for r in OSRelease.objects.select_related("operating_system"):
                    key = (r.operating_system.slug, r.version, r.channel)
                    if key not in seed_release_keys:
                        if not quiet:
                            self.stdout.write(f"  [prune] OSRelease: "
                                              f"{key[0]}@{key[1]}/{key[2]}")
                        r.delete()
                        pruned["release"] += 1
                for img in UpstreamImage.objects.select_related(
                    "release", "release__operating_system", "hardware_target",
                ):
                    key = (
                        img.release.operating_system.slug,
                        img.release.version,
                        img.release.channel,
                        img.hardware_target.slug,
                        img.variant,
                    )
                    if key not in seed_image_keys:
                        if not quiet:
                            self.stdout.write(
                                f"  [prune] UpstreamImage: "
                                f"{key[0]}@{key[1]} {key[3]} {key[4] or '(none)'}"
                            )
                        img.delete()
                        pruned["image"] += 1

        msg = (
            f"Seeded: {report['arch']} archs ({report['arch+']} new), "
            f"{report['target']} targets ({report['target+']} new), "
            f"{report['os']} OSes ({report['os+']} new), "
            f"{report['release']} releases ({report['release+']} new), "
            f"{report['image']} images ({report['image+']} new)."
        )
        if prune:
            msg += (f" Pruned {pruned['release']} releases, "
                    f"{pruned['image']} images.")
        self.stdout.write(self.style.SUCCESS(msg))

    def _echo(self, kind: str, identifier: str, created: bool) -> None:
        verb = "created" if created else "exists "
        self.stdout.write(f"  [{verb}] {kind}: {identifier}")
