"""Seed the catalog with the supported OS / hardware / release / image matrix.

Documented in ``docs/catalog.md``. Idempotent — every row uses
``get_or_create`` so running it again after upstream version bumps just adds
the new releases / images without disturbing the existing ones.

Usage:

    python manage.py seed_catalog
    python manage.py seed_catalog --quiet
"""

from __future__ import annotations

import datetime
import re
from typing import NamedTuple

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.deletion import ProtectedError

# Known release dates for OSes whose version isn't itself a date. Date-versioned
# OSes (raspios = YYYY-MM-DD) are derived from the version automatically.
KNOWN_RELEASE_DATES: dict[tuple[str, str], str] = {
    ("ubuntu", "26.04"): "2026-04-23",
    ("ubuntu", "24.04"): "2024-04-25",
    ("ubuntu", "22.04"): "2022-04-21",
    ("debian", "13"): "2025-08-09",
    ("debian", "12"): "2023-06-10",
    ("popos", "22.04"): "2022-04-25",
    # Batocera — from https://batocera.org/changelog (version - date - codename).
    ("batocera", "43.1"): "2026-05-30",
    ("batocera", "43"): "2026-05-08",
    ("batocera", "42"): "2025-10-12",
    ("batocera", "39"): "2024-03-04",
}


# Upstream changelog / release-notes page per OS — linked from each image.
CHANGELOG_URLS: dict[str, str] = {
    "batocera": "https://batocera.org/changelog",
    "raspios": "https://www.raspberrypi.com/software/operating-systems/",
    "ubuntu": "https://wiki.ubuntu.com/Releases",
    "debian": "https://www.debian.org/releases/",
    "haos": "https://github.com/home-assistant/operating-system/releases",
    "kali": "https://www.kali.org/releases/",
    "popos": "https://github.com/pop-os/iso/releases",
    "omarchy": "https://omarchy.org/",
    "l4t": "https://developer.nvidia.com/embedded/jetson-linux",
    "proxmox-ve": "https://pve.proxmox.com/wiki/Roadmap",
    "esphome": "https://esphome.io/changelog/",
    "windows": "https://learn.microsoft.com/windows/release-health/",
    "android": "https://developer.android.com/about/versions",
}


def _release_date(os_slug: str, version: str) -> datetime.date | None:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", version):
        return datetime.date.fromisoformat(version)
    known = KNOWN_RELEASE_DATES.get((os_slug, version))
    return datetime.date.fromisoformat(known) if known else None

from catalog.models import (
    Architecture,
    HardwareTarget,
    OperatingSystem,
    OSRelease,
    Provisioner,
    UpstreamImage,
    WorkflowStep,
)

# Default bake workflow per provisioner: ordered container steps that hand the
# image through S3 (work/<build_id>/…), last step publishes the artifact —
# rendered into an Argo Workflow per build. Images are placeholders until the
# per-step images are built/published.
_STEP_IMG = "ghcr.io/cznewt/os-bakery-step-{}:latest"
WORKFLOW_STEPS: dict[str, list[tuple[str, str, str]]] = {
    "salt": [
        ("fetch-base", _STEP_IMG.format("fetch"), "Fetch + decompress the base image into S3 work/."),
        ("provision", _STEP_IMG.format("salt"), "salt-call --local against the recipe states in a (qemu) chroot."),
        ("pack", _STEP_IMG.format("pack"), "Repack the provisioned rootfs to .img.xz."),
        ("push-s3", _STEP_IMG.format("push"), "Publish the artifact to the bucket + mint a download token."),
    ],
    "ansible": [
        ("fetch-base", _STEP_IMG.format("fetch"), "Fetch + decompress the base image into S3 work/."),
        ("provision", _STEP_IMG.format("ansible"), "ansible-playbook against the mounted rootfs."),
        ("pack", _STEP_IMG.format("pack"), "Repack the provisioned rootfs to .img.xz."),
        ("push-s3", _STEP_IMG.format("push"), "Publish the artifact to the bucket + mint a download token."),
    ],
    "cloud-init": [
        ("fetch-base", _STEP_IMG.format("fetch"), "Fetch + decompress the base image into S3 work/."),
        ("provision", _STEP_IMG.format("cloud-init"), "Inject cloud-init user-data/config into the image."),
        ("pack", _STEP_IMG.format("pack"), "Repack the image to .img.xz."),
        ("push-s3", _STEP_IMG.format("push"), "Publish the artifact to the bucket + mint a download token."),
    ],
}


# ---------------------------------------------------------------------------
# Provisioners — how a recipe customizes the image. Each lists the "states"
# (units) it can apply: Salt formulas, Ansible roles, or cloud-init modules.
# ---------------------------------------------------------------------------
PROVISIONERS: list[dict] = [
    {
        "slug": "salt",
        "name": "Salt",
        "is_default": True,
        "description": "Masterless salt-call --local applies the recipe's state "
                       "formulas inside the (qemu) chroot.",
        "available_states": [
            {"slug": "base.locale", "name": "Locale & timezone"},
            {"slug": "base.users", "name": "Admin user + SSH keys"},
            {"slug": "base.hardening", "name": "SSH/sshd hardening + ufw"},
            {"slug": "base.network", "name": "Wi-Fi / network config"},
            {"slug": "raspios.base", "name": "Raspberry Pi OS baseline"},
            {"slug": "raspios.headless", "name": "Headless (no desktop)"},
            {"slug": "raspios.docker", "name": "Docker on raspios"},
            {"slug": "raspios.kiosk", "name": "Kiosk mode"},
            {"slug": "ubuntu.base", "name": "Ubuntu baseline"},
            {"slug": "ubuntu.server", "name": "Ubuntu server"},
            {"slug": "ubuntu.k3s", "name": "k3s node"},
            {"slug": "batocera.base", "name": "Batocera baseline"},
            {"slug": "batocera.arcade", "name": "Arcade cabinet lockdown"},
            {"slug": "batocera.minimal", "name": "Minimal Batocera"},
            {"slug": "batocera.family", "name": "Family-friendly Batocera"},
            {"slug": "haos.base", "name": "Home Assistant OS baseline"},
            {"slug": "haos.network", "name": "HAOS network"},
            {"slug": "haos.ssh", "name": "HAOS SSH access"},
        ],
    },
    {
        "slug": "ansible",
        "name": "Ansible",
        "is_default": False,
        "description": "Apply Ansible roles against the mounted rootfs "
                       "(ansible-playbook --connection=chroot).",
        "available_states": [
            {"slug": "common", "name": "Common baseline"},
            {"slug": "users", "name": "Users & SSH keys"},
            {"slug": "hardening", "name": "Security hardening"},
            {"slug": "network", "name": "Network / Wi-Fi"},
            {"slug": "docker", "name": "Docker engine"},
            {"slug": "k3s", "name": "k3s node"},
            {"slug": "salt_minion", "name": "Salt minion"},
        ],
    },
    {
        "slug": "cloud-init",
        "name": "Cloud-Init",
        "is_default": False,
        "description": "Inject a cloud-init user-data/config so the image "
                       "self-configures on first boot.",
        "available_states": [
            {"slug": "users", "name": "users (accounts + SSH keys)"},
            {"slug": "ssh", "name": "ssh (host keys, authorized_keys)"},
            {"slug": "packages", "name": "packages (apt/yum install)"},
            {"slug": "package_update_upgrade", "name": "package update/upgrade"},
            {"slug": "write_files", "name": "write_files"},
            {"slug": "runcmd", "name": "runcmd"},
            {"slug": "hostname", "name": "set_hostname / fqdn"},
            {"slug": "timezone", "name": "timezone"},
            {"slug": "locale", "name": "locale"},
            {"slug": "network", "name": "network-config (netplan)"},
        ],
    },
]


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
    image_url: str = ""  # product photo URL (used by /devices/ cards)


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
    # Extra hardware targets that run this exact same image (no separate row),
    # e.g. the batocera x86_64 build shared by steamdeck + loki-zero.
    extra_targets: tuple[str, ...] = ()


ARCHITECTURES: list[ArchSeed] = [
    ArchSeed("arm64", "ARM 64-bit (aarch64)", "arm", 64),
    ArchSeed("armhf", "ARM 32-bit hard-float (armv7l)", "arm", 32),
    ArchSeed("amd64", "x86 64-bit (x86_64)", "x86", 64),
    # Microcontroller architectures
    ArchSeed("xtensa", "Tensilica Xtensa", "other", 32),
    ArchSeed("riscv32", "RISC-V 32-bit", "riscv", 32),
]

HARDWARE_TARGETS: list[TargetSeed] = [
    TargetSeed("rpi3", "Raspberry Pi 3", "arm64", "rpi", soc="BCM2837",
               notes="Pi 3 B / 3B+ / 3A+. arm64-capable.",
               image_url="https://batocera.org/images/download/rpi3b.png"),
    TargetSeed("rpi4", "Raspberry Pi 4", "arm64", "rpi", soc="BCM2711",
               notes="Pi 4 (1-8 GB) and Pi 400.",
               image_url="https://batocera.org/images/download/rpi4b.png"),
    TargetSeed("rpi5", "Raspberry Pi 5", "arm64", "rpi", soc="BCM2712",
               notes="Pi 5.",
               image_url="https://batocera.org/images/download/rpi5b.png"),
    TargetSeed("pc-amd64", "Generic x86_64 PC (UEFI)", "amd64", "uefi",
               notes="Laptops, mini PCs, NUC-class.",
               image_url="https://batocera.org/images/download/x86_64_models.png"),
    TargetSeed("pc-arm64", "Generic ARM64 PC (UEFI)", "arm64", "uefi",
               notes="Cloud VMs, Ampere, generic non-Pi ARM64 boards."),
    TargetSeed("vm-qemu", "QEMU / KVM virtual machine", "amd64", "uefi"),
    TargetSeed("vm-hyperv", "Microsoft Hyper-V Gen2", "amd64", "uefi"),
    TargetSeed("vm-virtualbox", "Oracle VirtualBox", "amd64", "bios"),
    TargetSeed("vm-vmware", "VMware ESXi / vSphere / Workstation", "amd64", "uefi",
               notes="HAOS OVA appliance for VMware."),
    # macOS hosts.
    TargetSeed("mac-apple-silicon", "Apple silicon Mac", "arm64", "uefi",
               soc="Apple M-series", notes="M1/M2/M3/M4 Macs (arm64)."),
    TargetSeed("mac-intel", "Intel Mac", "amd64", "uefi",
               notes="2020-and-earlier Intel Macs (x86_64)."),
    # Home Assistant OS appliance boards (per the alternative install page).
    TargetSeed("ha-yellow", "Home Assistant Yellow", "arm64", "uboot",
               soc="Raspberry Pi CM4", notes="HA Yellow (CM4 carrier)."),
    TargetSeed("ha-green", "Home Assistant Green", "arm64", "uboot",
               soc="Rockchip RK3566", notes="HA Green turnkey appliance."),
    TargetSeed("odroid-n2", "Hardkernel ODROID-N2/N2+", "arm64", "uboot",
               soc="Amlogic S922X"),
    TargetSeed("odroid-m1", "Hardkernel ODROID-M1", "arm64", "uboot",
               soc="Rockchip RK3568"),
    TargetSeed("odroid-c4", "Hardkernel ODROID-C4", "arm64", "uboot",
               soc="Amlogic S905X3"),
    TargetSeed("beaglebone-black", "BeagleBone Black", "armhf", "uboot",
               soc="TI AM335x",
               notes="1 GHz Cortex-A8. Boots from eMMC / SD. armhf only.",
               image_url="https://upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Beaglebone_Black_-_Top_%2814491195107%29.jpg/500px-Beaglebone_Black_-_Top_%2814491195107%29.jpg"),
    TargetSeed("beaglebone-blue", "BeagleBone Blue", "armhf", "uboot",
               soc="TI AM335x",
               notes="Robotics-focused BeagleBone Black variant — adds IMU, "
                     "barometer, motor drivers."),
    TargetSeed("jetson-nano", "NVIDIA Jetson Nano", "arm64", "uboot",
               soc="Tegra X1",
               notes="L4T (Linux for Tegra) only — the Tegra kernel is "
                     "Ubuntu-based but not interchangeable with stock arm64. "
                     "Last supported L4T: r32.7.x.",
               image_url="https://upload.wikimedia.org/wikipedia/commons/thumb/9/9a/NVIDIA_Jetson_Nano_Developer_Kit_%2840650425603%29.jpg/500px-NVIDIA_Jetson_Nano_Developer_Kit_%2840650425603%29.jpg"),
    TargetSeed("jetson-xavier-nx", "NVIDIA Jetson Xavier NX", "arm64", "uboot",
               soc="Tegra Xavier",
               notes="L4T r35.x. Lower-power Xavier module for the dev kit."),
    TargetSeed("jetson-orin-nano", "NVIDIA Jetson Orin Nano", "arm64", "uboot",
               soc="Tegra Orin",
               notes="Current Jetson dev kit (8 GB / 4 GB). L4T r36.x."),
    # ---- Retro handhelds (Batocera per-device builds) -----------------
    TargetSeed("rg552", "Anbernic RG552", "arm64", "uboot",
               soc="Rockchip RK3399",
               notes="Dual-screen Anbernic flagship handheld.",
               image_url="https://batocera.org/images/download/rg552.png"),
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
    TargetSeed("loki-zero", "AYN Loki Zero", "amd64", "uefi",
               soc="AMD Mendocino",
               notes="AYN Loki Zero — x86-64 (AMD) budget handheld; runs the "
                     "batocera x86_64 zen build.",
               image_url="https://batocera.org/images/download/lokizero.png"),
    TargetSeed("steamdeck", "Valve Steam Deck", "amd64", "uefi",
               soc="AMD Aerith/Sephiroth",
               notes="Valve Steam Deck — x86-64 handheld; runs the batocera "
                     "x86_64 zen build."),
    TargetSeed("flip-2", "Retroid Pocket Flip 2", "arm64", "uboot",
               notes="Clamshell flip-style handheld (per Batocera download page).",
               image_url="https://batocera.org/images/download/rpflip2.png"),
    TargetSeed("pocket-5", "Retroid Pocket 5", "arm64", "uboot",
               notes="Retroid Pocket 5 handheld (per Batocera download page).",
               image_url="https://batocera.org/images/download/rp5.png"),
    TargetSeed("ayn-odin-2", "AYN Odin 2", "arm64", "custom",
               soc="Qualcomm Snapdragon 8 Gen 2 (SM8550)",
               notes="High-end Android-based handheld — also runs Batocera "
                     "via the per-device build on batocera.org/download. "
                     "Odin 2 / Odin 2 Mini / Odin 2 Pro share this target.",
               image_url="https://batocera.org/images/download/odin2.png"),
    # ---- Mobile (Android phones / tablets) -----------------------------
    # arm64 + custom boot (Android's own bootloader). These are registered as
    # nodes for VPN / device management — os-bakery doesn't image them, so they
    # have no OSRelease / UpstreamImage rows.
    TargetSeed("phone-arm64", "Android phone (ARM64)", "arm64", "custom",
               soc="ARM64 SoC (Snapdragon / Tensor / Exynos / MediaTek)",
               notes="Generic ARM64 Android smartphone."),
    TargetSeed("tablet-arm64", "Android tablet (ARM64)", "arm64", "custom",
               soc="ARM64 SoC (Snapdragon / Tensor / Exynos / MediaTek)",
               notes="Generic ARM64 Android tablet."),
    # ---- ESPHome microcontroller targets -------------------------------
    TargetSeed("esp32", "Espressif ESP32", "xtensa", "custom",
               soc="ESP32 (Xtensa LX6, 240 MHz dual-core, Wi-Fi + BLE)",
               notes="Original ESP32 generation."),
    TargetSeed("esp32-s3", "Espressif ESP32-S3", "xtensa", "custom",
               soc="ESP32-S3 (Xtensa LX7, 240 MHz dual-core, USB-OTG)",
               notes="USB-OTG, AI accelerator vector instructions, more PSRAM."),
    TargetSeed("esp32-c3", "Espressif ESP32-C3", "riscv32", "custom",
               soc="ESP32-C3 (RISC-V, 160 MHz single-core, BLE5)",
               notes="Low-cost RISC-V chip, BLE 5 + Wi-Fi 4."),
    TargetSeed("esp32-c6", "Espressif ESP32-C6", "riscv32", "custom",
               soc="ESP32-C6 (RISC-V, 160 MHz, 802.15.4 + Wi-Fi 6)",
               notes="Adds Thread / Zigbee 802.15.4 radio."),
    TargetSeed("esp8266", "Espressif ESP8266", "xtensa", "custom",
               soc="ESP8266 (Xtensa LX106, 80 MHz, Wi-Fi only)",
               notes="Legacy; many Shelly / Sonoff / Wemos boards."),
    # ---- ESP dev boards ------------------------------------------------
    TargetSeed("esp32-devkit", "Espressif ESP32-DevKitC", "xtensa", "custom",
               soc="ESP32 (Xtensa LX6)",
               notes="Reference ESP32 dev board with USB-UART bridge.",
               image_url="https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/ESP32_Dev_Board.jpg/500px-ESP32_Dev_Board.jpg"),
    TargetSeed("esp32-s3-devkit", "Espressif ESP32-S3-DevKitC", "xtensa", "custom",
               soc="ESP32-S3 (Xtensa LX7)",
               notes="Reference ESP32-S3 dev board, USB-OTG ready."),
    TargetSeed("esp32-c3-devkit", "Espressif ESP32-C3-DevKitM", "riscv32", "custom",
               soc="ESP32-C3 (RISC-V)",
               notes="Reference ESP32-C3 dev board, RISC-V single-core."),
    TargetSeed("esp32-c6-devkit", "Espressif ESP32-C6-DevKitC", "riscv32", "custom",
               soc="ESP32-C6 (RISC-V)",
               notes="Reference ESP32-C6 dev board with 802.15.4 radio."),
    TargetSeed("esp8266-nodemcu", "NodeMCU ESP8266", "xtensa", "custom",
               soc="ESP8266 (Xtensa LX106)",
               notes="Classic NodeMCU dev board — ESP-12E module + USB-UART.",
               image_url="https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/NodeMCU_DEVKIT_1.0.jpg/500px-NodeMCU_DEVKIT_1.0.jpg"),
    # ---- Vendor devices (https://github.com/Craftama/esphome-models) ---
    TargetSeed("ai-thinker-esp32-cam", "AI-Thinker ESP32-CAM", "xtensa", "custom",
               soc="ESP32 (Xtensa LX6)",
               notes="ESP32 + OV2640 camera + microSD socket.",
               image_url="https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/ESP32-CAM.jpg/500px-ESP32-CAM.jpg"),
    TargetSeed("athom-ps01", "Athom PS01 smart plug", "xtensa", "custom",
               soc="ESP32 (Xtensa LX6)",
               notes="EU/US smart plug with energy metering."),
    TargetSeed("laskakit-esplan", "LaskaKit ESPlan", "xtensa", "custom",
               soc="ESP32 (Xtensa LX6) + W5500 Ethernet",
               notes="ESP32 with on-board Ethernet — popular wired HA node."),
    TargetSeed("laskakit-vindriktning", "LaskaKit Vindriktning add-on", "xtensa", "custom",
               soc="ESP32 (Xtensa LX6)",
               notes="ESP32 add-on board that plugs inside the IKEA "
                     "Vindriktning air-quality sensor."),
    TargetSeed("m5stack-atoms3", "M5Stack AtomS3", "xtensa", "custom",
               soc="ESP32-S3 (Xtensa LX7)",
               notes="Tiny ESP32-S3 module with display + button."),
    TargetSeed("shelly-1", "Shelly 1", "xtensa", "custom",
               soc="ESP8266 (Xtensa LX106)",
               notes="Compact relay flashable via TTL — OTA after first bake."),
    TargetSeed("sonoff-mini", "Sonoff Mini R3", "xtensa", "custom",
               soc="ESP32 (Xtensa LX6)",
               notes="In-wall switch behind existing toggles. R3 = ESP32."),
    TargetSeed("sonoff-4ch-pro", "Sonoff 4CH Pro R2", "xtensa", "custom",
               soc="ESP8266 (Xtensa LX106)",
               notes="4-channel DIN-rail Sonoff relay."),
    TargetSeed("sonoff-nspanel", "Sonoff NSPanel", "xtensa", "custom",
               soc="ESP32 (Xtensa LX6)",
               notes="Wall-mount smart panel with touchscreen."),
    TargetSeed("sonoff-s20", "Sonoff S20", "xtensa", "custom",
               soc="ESP8266 (Xtensa LX106)",
               notes="Classic smart plug, EU/UK/US variants."),
    TargetSeed("ulanzi-tc001", "Ulanzi TC001 pixel clock", "xtensa", "custom",
               soc="ESP32 (Xtensa LX6)",
               notes="32×8 RGB matrix smart clock — AWTRIX firmware "
                     "compatible.",
               image_url="https://upload.wikimedia.org/wikipedia/commons/9/94/Ulanzi.jpg"),
    TargetSeed("weber-igrill-v2", "Weber iGrill v2", "xtensa", "custom",
               soc="ESP32 (Xtensa LX6)",
               notes="BLE companion / replacement firmware for the Weber "
                     "iGrill v2 thermometer."),
    TargetSeed("wemos-d1-mini", "Wemos D1 mini", "xtensa", "custom",
               soc="ESP8266 (Xtensa LX106)",
               notes="Tiny low-cost ESP8266 board — community staple.",
               image_url="https://upload.wikimedia.org/wikipedia/commons/thumb/4/40/WeMos_D1_Mini_front.jpg/500px-WeMos_D1_Mini_front.jpg"),
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
    OSSeed("esphome", "ESPHome", "Open Home Foundation", "iot",
           homepage="https://esphome.io",
           summary="YAML-driven firmware compiler for ESP32 / ESP8266 — "
                   "ships flashable .bin images per device profile."),
    OSSeed("windows", "Windows", "Microsoft", "desktop",
           homepage="https://www.microsoft.com/windows",
           summary="Microsoft Windows. Installer ISOs come with autounattend.xml "
                   "preseed so the bake yields a one-touch install image."),
    OSSeed("macos", "macOS", "Apple", "desktop",
           homepage="https://www.apple.com/macos/",
           summary="Apple macOS. Installer downloads (InstallAssistant / IPSW) "
                   "are gated, so URLs are placeholders; the macos salt formula "
                   "applies locale, users and packages on first boot."),
    OSSeed("android", "Android", "Google / AOSP", "mobile",
           homepage="https://www.android.com",
           summary="Google Android for phones and tablets. os-bakery doesn't "
                   "image Android — it's modelled so phones/tablets can be "
                   "registered as nodes (e.g. to set up a WireGuard client)."),
]

RELEASES: list[ReleaseSeed] = [
    # Batocera — current 43 default + 42 + a v39 row for hardware stuck on
    # the legacy build (RG552 stopped at 39).
    ReleaseSeed("batocera", "39", "stable", codename="Painted Lady"),
    ReleaseSeed("batocera", "42", "stable", codename="Papilio Ulysses"),
    ReleaseSeed("batocera", "43", "stable", codename="Glasswing"),
    # 43.1 — stability patch over 43 (no codename). Only the x86_64 builds got
    # a 43.1 image; the SBC/handheld builds stay on their 43/42/39 images.
    ReleaseSeed("batocera", "43.1", "stable", is_default=True),
    # Ubuntu — Jammy (22.04) is still in standard support until 2027; Noble
    # (24.04) is the headline LTS for new builds. 16.04 Xenial dropped (ESM
    # only, end-of-mainstream-support).
    ReleaseSeed("ubuntu", "22.04", "lts", codename="Jammy"),
    ReleaseSeed("ubuntu", "24.04", "lts", codename="Noble"),
    ReleaseSeed("ubuntu", "26.04", "lts", codename="Resolute", is_default=True),
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
    ReleaseSeed("raspios", "2025-05-13", "stable", codename="Bookworm"),
    # Latest — Raspberry Pi OS moved to Debian 13 (Trixie).
    ReleaseSeed("raspios", "2026-04-21", "stable", codename="Trixie",
                is_default=True),
    # Home Assistant OS — only the current major is supported.
    ReleaseSeed("haos", "17.3", "stable", is_default=True),
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
    # ESPHome — one firmware-toolchain release per ESPHome version. Keep
    # the current series + last LTS-ish; ESPHome doesn't publish LTS,
    # but device YAMLs occasionally pin older majors.
    ReleaseSeed("esphome", "2025.11.0", "stable"),
    ReleaseSeed("esphome", "2026.4.0", "stable", is_default=True),
    # Windows — Microsoft's installer ISOs; gated downloads, so URLs are
    # placeholders pointing at the download portal. Recipes preseed
    # autounattend.xml so the bake produces a one-touch install ISO.
    ReleaseSeed("windows", "11", "stable", codename="24H2", is_default=True),
    ReleaseSeed("windows", "10", "stable", codename="22H2"),
    # macOS — Apple's installer downloads are version-gated, so URLs are
    # placeholders. The macos salt formula does the on-first-boot config.
    ReleaseSeed("macos", "15", "stable", codename="Sequoia"),
    ReleaseSeed("macos", "26", "stable", codename="Tahoe", is_default=True),
]


# --- URL templates (kept inline so the seed file is the one source of truth)

# Batocera URLs are date-stamped per build (not "stable.img.gz" as the
# pattern would suggest) — scraped from https://batocera.org/download.
# Refresh when upstream cuts a new build. Bare /stable/last/ is a real
# directory; this resolves to whatever file is currently inside it.
# Two x86-64 batocera builds: the generic "full" PC image and the "zen"
# (x86-64-v3) build that the modern x86 handhelds (Steam Deck, AYN Loki) run.
_BATO_X64_FULL = "https://updates.batocera.org/x86_64/stable/last/batocera-x86_64-43.1-20260529.img.gz"
_BATO_X64_ZEN = "https://updates.batocera.org/x86-64-v3/stable/last/batocera-zen3-x86-64-v3-43.1-20260529.img.gz"
_RGXX3 = "https://updates.batocera.org/anbernic-rgxx3/stable/last/batocera-rk3568-anbernic-rgxx3-42-20251016.img.gz"

# (primary target, version, variant, url, extra_targets that share this image)
BATOCERA_IMAGES: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    # Single-board computers (43 = current default).
    ("rpi3",      "43", "", "https://updates.batocera.org/bcm2837/stable/last/batocera-bcm2837-43-20260508.img.gz", ()),
    ("rpi4",      "43", "", "https://updates.batocera.org/bcm2711/stable/last/batocera-bcm2711-43-20260501.img.gz", ()),
    ("rpi5",      "43", "", "https://updates.batocera.org/bcm2712/stable/last/batocera-bcm2712-43-20260430.img.gz", ()),
    # x86-64: two builds. "full" = generic PC; "zen" (x86-64-v3) is shared by
    # the modern x86 handhelds (Steam Deck + AYN Loki Zero). Both bumped to the
    # 43.1 stability patch (the SBC/handheld builds have no 43.1 image yet).
    ("pc-amd64",  "43.1", "full", _BATO_X64_FULL, ()),
    ("pc-amd64",  "43.1", "zen",  _BATO_X64_ZEN, ("steamdeck", "loki-zero")),
    # Anbernic RK3566 family — ONE rgxx3 image shared by the RG353 series
    # AND the RG503 (all Rockchip RK3566).
    ("rg353p",    "42", "", _RGXX3, ("rg353ps", "rg353v", "rg353vs", "rg503")),
    # RG552 — stuck on the legacy v39 RK3399 build.
    ("rg552",     "39", "", "https://updates.batocera.org/rg552/stable/last/batocera-rk3399-rg552-39-20240305.img.gz", ()),
    # Retroid Snapdragon-865 handhelds (Pocket 5 + Pocket Flip 2).
    ("pocket-5",  "42", "", "https://updates.batocera.org/rp5/stable/last/batocera-sm8250-rp5-42-20251011.img.gz", ()),
    ("flip-2",    "42", "", "https://updates.batocera.org/rpflip2/stable/last/batocera-sm8250-rpflip2-42-20251011.img.gz", ()),
    # SM8550 share-build (AYN Odin 2 on Snapdragon 8 Gen 2).
    ("ayn-odin-2", "43", "", "https://updates.batocera.org/sm8550/stable/last/batocera-sm8550-43-20260507.img.gz", ()),
]

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
    "26.04": "https://releases.ubuntu.com/26.04/ubuntu-26.04-desktop-amd64.iso",
}

# Debian — `/latest/` always resolves to the current point release.
_DEBIAN_CLOUD_AMD = "https://cloud.debian.org/images/cloud/{codename}/latest/debian-{major}-genericcloud-amd64.qcow2"
_DEBIAN_CLOUD_ARM = "https://cloud.debian.org/images/cloud/{codename}/latest/debian-{major}-genericcloud-arm64.qcow2"
# raspi.debian.net publishes per-Pi tested images.
_DEBIAN_RPI = "https://raspi.debian.net/tested-images/{codename}/raspi_{pi}_{codename}.img.xz"
# BeagleBoard.org publishes BeagleBone (am335x) Debian armhf images at
# files.beagle.cc (linked from beagleboard.org/distros). The filename carries
# a moving date stamp — this is the current latest as of 2026-05-19.
_DEBIAN_BBONE = (
    "https://files.beagle.cc/file/beagleboard-public-2021/images/"
    "am335x-debian-12.14-base-v6.12-armhf-2026-05-19-4gb.img.xz"
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

# ESPHome firmware factory — per ESPHome release + chip target, the project's
# build pipeline emits factory .bin images. Recipes layer device YAMLs on
# top at compile time; the upstream image is the chip-specific runtime.
_ESPHOME_FACTORY = (
    "https://github.com/esphome/esphome/releases/download/{release}/"
    "esphome-{release}-factory-{chip}.bin"
)

# Windows — Microsoft's signed download URLs expire; point at the portal
# and let the orchestrator's downloader follow the redirect chain.
_WINDOWS_ISO = "https://www.microsoft.com/software-download/windows{release}"

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
# platform) combo. Boards ship a flashable .img.xz; the VM/appliance images
# ship per-hypervisor (qcow2.xz / ova / vdi.zip / vhdx.zip).
_HAOS = (
    "https://github.com/home-assistant/operating-system/releases/download/"
    "{version}/haos_{platform}-{version}.img.xz"
)
_HAOS_VM = (
    "https://github.com/home-assistant/operating-system/releases/download/"
    "{version}/haos_ova-{version}.{ext}"
)
HAOS_VERSION = "17.3"


def _images() -> list[ImageSeed]:
    rows: list[ImageSeed] = []

    # Batocera — explicit per-target URLs because the upstream filename
    # is date-stamped (not "stable.img.gz") and per-device builds branch
    # off at different versions. See BATOCERA_IMAGES above.
    for target, version, variant, url, extra in BATOCERA_IMAGES:
        rows.append(ImageSeed(
            "batocera", version, "stable", target, variant, url, "img.gz",
            extra_targets=extra,
        ))

    # Ubuntu 22.04 (Jammy) + 24.04 (Noble) — same shape: raspi-preinstalled
    # for rpi4/5 × server/desktop, cloud for pc-arm64 + pc-amd64 server,
    # ISO for pc-amd64 desktop, cloud-image for VM targets.
    for release in ("22.04", "24.04", "26.04"):
        rows.append(ImageSeed("ubuntu", release, "lts", "pc-arm64",
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

    # Debian 13 Trixie — cloud images for pc-arm64 / pc-amd64 / VMs,
    # plus raspi.debian.net images for the Pi family.
    rows.append(ImageSeed("debian", "13", "stable", "pc-arm64", "server",
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

    # ESPHome — every dev board / vendor device maps to one of five ESP
    # chip families; the factory bin URL is per-chip but the catalog row is
    # per-device so recipes can pick the right pinout / GPIO map.
    esphome_targets = [
        # (HardwareTarget slug, underlying ESPHome chip platform)
        ("esp32",                 "esp32"),
        ("esp32-s3",              "esp32-s3"),
        ("esp32-c3",              "esp32-c3"),
        ("esp32-c6",              "esp32-c6"),
        ("esp8266",               "esp8266"),
        # Dev boards
        ("esp32-devkit",          "esp32"),
        ("esp32-s3-devkit",       "esp32-s3"),
        ("esp32-c3-devkit",       "esp32-c3"),
        ("esp32-c6-devkit",       "esp32-c6"),
        ("esp8266-nodemcu",       "esp8266"),
        ("wemos-d1-mini",         "esp8266"),
        # Vendor devices (from craftama/esphome-models)
        ("ai-thinker-esp32-cam",  "esp32"),
        ("athom-ps01",            "esp32"),
        ("laskakit-esplan",       "esp32"),
        ("laskakit-vindriktning", "esp32"),
        ("m5stack-atoms3",        "esp32-s3"),
        ("shelly-1",              "esp8266"),
        ("sonoff-mini",           "esp32"),
        ("sonoff-4ch-pro",        "esp8266"),
        ("sonoff-nspanel",        "esp32"),
        ("sonoff-s20",            "esp8266"),
        ("ulanzi-tc001",          "esp32"),
        ("weber-igrill-v2",       "esp32"),
    ]
    for esphome_release in ("2025.11.0", "2026.4.0"):
        for target, chip in esphome_targets:
            rows.append(ImageSeed(
                "esphome", esphome_release, "stable", target, "",
                _ESPHOME_FACTORY.format(release=esphome_release, chip=chip),
                "img",
            ))

    # Windows — same ISO usable on bare-metal pc-amd64 and the three VM
    # hypervisor targets (Hyper-V / VirtualBox / QEMU all install from it).
    for win_release in ("11", "10"):
        for target in ("pc-amd64", "vm-qemu", "vm-hyperv", "vm-virtualbox"):
            rows.append(ImageSeed(
                "windows", win_release, "stable", target, "",
                _WINDOWS_ISO.format(release=win_release), "iso",
            ))

    # macOS — no public direct installer URL (InstallAssistant / IPSW are
    # gated), so the source is a placeholder pointing at the macOS page; the
    # macos salt formula does the real work on first boot.
    for mac_release in ("15", "26"):
        for target in ("mac-apple-silicon", "mac-intel"):
            rows.append(ImageSeed(
                "macos", mac_release, "stable", target, "",
                "https://www.apple.com/macos/", "img",
            ))

    # RaspiOS — one image per arm64 variant per dated release; three Pi
    # targets share each image.
    raspios_dates = [
        ("2023-05-03", "bullseye"),
        ("2024-07-04", "bookworm"),
        ("2024-11-19", "bookworm"),
        ("2025-03-15", "bookworm"),
        ("2025-05-13", "bookworm"),
        ("2026-04-21", "trixie"),
    ]
    for date, codename in raspios_dates:
        desktop_url = _RASPIOS_DESKTOP.format(date=date, codename=codename)
        lite_url = _RASPIOS_LITE.format(date=date, codename=codename)
        for target in ("rpi3", "rpi4", "rpi5"):
            rows.append(ImageSeed("raspios", date, "stable", target,
                                  "desktop", desktop_url, "img.xz"))
            rows.append(ImageSeed("raspios", date, "stable", target,
                                  "lite", lite_url, "img.xz"))

    # HAOS — per-board appliance image (flashable .img.xz). One row per device
    # the project ships an image for (see the alternative-install page).
    haos_boards = [
        ("pc-amd64", "generic-x86-64"),
        ("pc-arm64", "generic-aarch64"),
        ("rpi3", "rpi3-64"),
        ("rpi4", "rpi4-64"),
        ("rpi5", "rpi5-64"),
        ("ha-yellow", "yellow"),
        ("ha-green", "green"),
        ("odroid-n2", "odroid-n2"),
        ("odroid-m1", "odroid-m1"),
        ("odroid-c4", "odroid-c4"),
    ]
    for target, platform in haos_boards:
        rows.append(ImageSeed(
            "haos", HAOS_VERSION, "stable", target, "",
            _HAOS.format(version=HAOS_VERSION, platform=platform),
            "img.xz",
        ))
    # HAOS — virtual-machine / hypervisor appliance images (alternative install).
    haos_vms = [
        ("vm-qemu", "qcow2.xz", "qcow2"),       # KVM / Proxmox / libvirt
        ("vm-vmware", "ova", "ova"),            # VMware ESXi / vSphere
        ("vm-virtualbox", "vdi.zip", "img.zip"),
        ("vm-hyperv", "vhdx.zip", "img.zip"),
    ]
    for target, ext, fmt in haos_vms:
        rows.append(ImageSeed(
            "haos", HAOS_VERSION, "stable", target, "",
            _HAOS_VM.format(version=HAOS_VERSION, ext=ext), fmt,
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
            for pseed in PROVISIONERS:
                obj, created = Provisioner.objects.update_or_create(
                    slug=pseed["slug"],
                    defaults=dict(
                        name=pseed["name"],
                        description=pseed["description"],
                        is_default=pseed["is_default"],
                        available_states=pseed["available_states"],
                    ),
                )
                if not quiet:
                    self._echo("Provisioner", obj.slug, created)
                # Sync the provisioner's ordered workflow steps.
                for order, (name, image, desc) in enumerate(WORKFLOW_STEPS.get(pseed["slug"], [])):
                    WorkflowStep.objects.update_or_create(
                        provisioner=obj, order=order,
                        defaults=dict(name=name, image=image, description=desc),
                    )

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
                        image_url=tseed.image_url,
                    ),
                )
                # The seed is the source of truth — refresh core fields on
                # existing rows too (name, arch, boot, soc, notes, image_url).
                if not created:
                    want = dict(
                        name=tseed.name,
                        architecture=arch_by_slug[tseed.architecture],
                        boot_method=tseed.boot_method,
                        soc=tseed.soc,
                        notes=tseed.notes,
                        image_url=tseed.image_url,
                    )
                    changed = [f for f, v in want.items() if getattr(obj, f) != v]
                    if changed:
                        for f, v in want.items():
                            setattr(obj, f, v)
                        obj.save(update_fields=changed)
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
                changelog = CHANGELOG_URLS.get(oseed.slug, "")
                if changelog and obj.changelog_url != changelog:
                    obj.changelog_url = changelog
                    obj.save(update_fields=["changelog_url"])
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
                # get_or_create defaults only apply on create — keep codename
                # and the backfilled release date in sync for existing rows too.
                changed: list[str] = []
                if rseed.codename and obj.codename != rseed.codename:
                    obj.codename = rseed.codename
                    changed.append("codename")
                rel_date = _release_date(rseed.os_slug, rseed.version)
                if rel_date and obj.released_on != rel_date:
                    obj.released_on = rel_date
                    changed.append("released_on")
                if changed:
                    obj.save(update_fields=changed)
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
                # Refresh source_url + format on existing rows so re-seeding
                # picks up upstream URL changes (e.g. a new Batocera build's
                # date-stamped filename).
                changed = []
                if not created and obj.source_url != iseed.source_url:
                    obj.source_url = iseed.source_url
                    changed.append("source_url")
                if not created and obj.format != iseed.format:
                    obj.format = iseed.format
                    changed.append("format")
                if changed:
                    obj.save(update_fields=changed)
                # Extra devices that share this exact image (M2M).
                extra = [target_by_slug[s] for s in iseed.extra_targets
                         if s in target_by_slug]
                obj.extra_targets.set(extra)
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
        kept = {"release": 0, "image": 0}
        if prune:
            seed_release_keys = {
                (r.os_slug, r.version, r.channel) for r in RELEASES
            }
            seed_image_keys = {
                (i.os_slug, i.release_version, i.release_channel,
                 i.target_slug, i.variant) for i in _images()
            }
            # Prune images BEFORE releases so a dropped release whose images are
            # all gone can then be removed too. Anything still pinned by a build
            # (PROTECT) is kept rather than crashing the seed — e.g. a succeeded
            # build holds haos@17.1 long after the seed moves on to 17.3. Each
            # delete gets its own savepoint so one protected row doesn't poison
            # the rest of the prune.
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
                    label = f"{key[0]}@{key[1]} {key[3]} {key[4] or '(none)'}"
                    try:
                        with transaction.atomic():
                            img.delete()
                        pruned["image"] += 1
                        if not quiet:
                            self.stdout.write(f"  [prune] UpstreamImage: {label}")
                    except ProtectedError:
                        kept["image"] += 1
                        if not quiet:
                            self.stdout.write(
                                f"  [keep ] UpstreamImage pinned by a build: {label}"
                            )
            for r in OSRelease.objects.select_related("operating_system"):
                key = (r.operating_system.slug, r.version, r.channel)
                if key not in seed_release_keys:
                    label = f"{key[0]}@{key[1]}/{key[2]}"
                    try:
                        with transaction.atomic():
                            r.delete()
                        pruned["release"] += 1
                        if not quiet:
                            self.stdout.write(f"  [prune] OSRelease: {label}")
                    except ProtectedError:
                        kept["release"] += 1
                        if not quiet:
                            self.stdout.write(
                                f"  [keep ] OSRelease pinned by a build: {label}"
                            )

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
            if kept["release"] or kept["image"]:
                msg += (f" Kept {kept['release']} releases + {kept['image']} "
                        f"images still pinned by builds.")
        self.stdout.write(self.style.SUCCESS(msg))

    def _echo(self, kind: str, identifier: str, created: bool) -> None:
        verb = "created" if created else "exists "
        self.stdout.write(f"  [{verb}] {kind}: {identifier}")
