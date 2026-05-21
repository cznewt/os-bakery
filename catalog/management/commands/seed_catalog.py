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
]

OPERATING_SYSTEMS: list[OSSeed] = [
    OSSeed("batocera", "Batocera.linux", "Batocera community", "retro",
           homepage="https://batocera.org",
           summary="Read-only retro-gaming OS with per-Pi builds."),
    OSSeed("ubuntu", "Ubuntu", "Canonical", "server",
           homepage="https://ubuntu.com",
           summary="General-purpose Linux; desktop / server / cloud variants."),
    OSSeed("raspios", "Raspberry Pi OS", "Raspberry Pi Ltd.", "desktop",
           homepage="https://www.raspberrypi.com/software/",
           summary="Debian-based OS for the Raspberry Pi family."),
    OSSeed("haos", "Home Assistant OS", "Open Home Foundation", "iot",
           homepage="https://www.home-assistant.io/installation/",
           summary="Immutable container OS for the Home Assistant stack."),
]

RELEASES: list[ReleaseSeed] = [
    ReleaseSeed("batocera", "41", "stable", is_default=True),
    ReleaseSeed("ubuntu", "24.04", "lts", codename="Noble", is_default=True),
    ReleaseSeed("raspios", "2025-05-13", "stable", codename="Bookworm",
                is_default=True),
    ReleaseSeed("haos", "14.2", "stable", is_default=True),
]


# --- URL templates (kept inline so the seed file is the one source of truth)

_BATOCERA = "https://updates.batocera.org/{platform}/stable/last/batocera-{platform}-41-stable.img.gz"
_UBUNTU_RPI = "https://cdimage.ubuntu.com/releases/24.04/release/ubuntu-24.04-preinstalled-{variant}-arm64+raspi.img.xz"
_UBUNTU_CLOUD_ARM = "https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-arm64.img"
_UBUNTU_CLOUD_AMD = "https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img"
_UBUNTU_DESKTOP_AMD = "https://releases.ubuntu.com/24.04/ubuntu-24.04.1-desktop-amd64.iso"
_RASPIOS_DESKTOP = (
    "https://downloads.raspberrypi.com/raspios_arm64/images/"
    "raspios_arm64-2025-05-13/2025-05-13-raspios-bookworm-arm64.img.xz"
)
_RASPIOS_LITE = (
    "https://downloads.raspberrypi.com/raspios_lite_arm64/images/"
    "raspios_lite_arm64-2025-05-13/2025-05-13-raspios-bookworm-arm64-lite.img.xz"
)
_HAOS = (
    "https://github.com/home-assistant/operating-system/releases/download/"
    "14.2/haos_{platform}-14.2.img.xz"
)


def _images() -> list[ImageSeed]:
    rows: list[ImageSeed] = []

    # Batocera 41 — one image per target, no variant.
    for target, platform in [
        ("rpi3", "bcm2710"),
        ("rpi4", "bcm2711"),
        ("rpi5", "bcm2712"),
        ("pc-amd64", "x86_64"),
    ]:
        rows.append(ImageSeed(
            "batocera", "41", "stable", target, "",
            _BATOCERA.format(platform=platform), "img.gz",
        ))

    # Ubuntu 24.04 — server / desktop, raspi-preinstalled / cloud / desktop ISO.
    rows.append(ImageSeed("ubuntu", "24.04", "lts", "generic-arm64",
                          "server", _UBUNTU_CLOUD_ARM, "img"))
    for target in ("rpi4", "rpi5"):
        rows.append(ImageSeed("ubuntu", "24.04", "lts", target, "server",
                              _UBUNTU_RPI.format(variant="server"), "img.xz"))
        rows.append(ImageSeed("ubuntu", "24.04", "lts", target, "desktop",
                              _UBUNTU_RPI.format(variant="desktop"), "img.xz"))
    rows.append(ImageSeed("ubuntu", "24.04", "lts", "pc-amd64",
                          "server", _UBUNTU_CLOUD_AMD, "img"))
    rows.append(ImageSeed("ubuntu", "24.04", "lts", "pc-amd64",
                          "desktop", _UBUNTU_DESKTOP_AMD, "iso"))
    # VM targets reuse the amd64 cloud image; format conversion is a packer
    # post-processor concern, not a different upstream URL.
    for target in ("vm-qemu", "vm-hyperv", "vm-virtualbox"):
        rows.append(ImageSeed("ubuntu", "24.04", "lts", target,
                              "server", _UBUNTU_CLOUD_AMD, "img"))

    # RaspiOS Bookworm — one image per arm64 variant, three Pi targets share it.
    for target in ("rpi3", "rpi4", "rpi5"):
        rows.append(ImageSeed("raspios", "2025-05-13", "stable", target,
                              "desktop", _RASPIOS_DESKTOP, "img.xz"))
        rows.append(ImageSeed("raspios", "2025-05-13", "stable", target,
                              "lite", _RASPIOS_LITE, "img.xz"))

    # HAOS 14.2 — per-target appliance image, no variant.
    for target, platform in [
        ("rpi4", "rpi4-64"),
        ("rpi5", "rpi5-64"),
        ("pc-amd64", "generic-x86-64"),
    ]:
        rows.append(ImageSeed("haos", "14.2", "stable", target, "",
                              _HAOS.format(platform=platform), "img.xz"))

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

    def handle(self, *args, quiet: bool = False, **options) -> None:
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

        self.stdout.write(self.style.SUCCESS(
            f"Seeded: {report['arch']} archs ({report['arch+']} new), "
            f"{report['target']} targets ({report['target+']} new), "
            f"{report['os']} OSes ({report['os+']} new), "
            f"{report['release']} releases ({report['release+']} new), "
            f"{report['image']} images ({report['image+']} new)."
        ))

    def _echo(self, kind: str, identifier: str, created: bool) -> None:
        verb = "created" if created else "exists "
        self.stdout.write(f"  [{verb}] {kind}: {identifier}")
