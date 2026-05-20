"""Catalog of operating systems, releases, target hardware, and upstream images.

These tables describe **what** can be baked. They're the read-mostly side of the
domain — populated by humans or sync jobs that crawl upstream release pages and
by Packer when it refreshes a base image.
"""

from __future__ import annotations

from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Architecture(TimestampedModel):
    """CPU architecture / ABI a built image targets."""

    class Family(models.TextChoices):
        ARM = "arm", _("ARM")
        X86 = "x86", _("x86")
        RISCV = "riscv", _("RISC-V")
        OTHER = "other", _("Other")

    slug = models.SlugField(unique=True, help_text="e.g. arm64, armv7l, amd64, i686")
    name = models.CharField(max_length=80, help_text="Human label, e.g. 'ARM 64-bit (aarch64)'")
    family = models.CharField(max_length=16, choices=Family.choices, default=Family.OTHER)
    bits = models.PositiveSmallIntegerField(default=64)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["family", "slug"]

    def __str__(self) -> str:
        return self.name


class HardwareTarget(TimestampedModel):
    """A specific board, SoC, or PC profile we publish images for.

    A HardwareTarget binds an :class:`Architecture` with a concrete boot/firmware
    expectation. Recipes declare which targets they support; Packer templates
    declare which target they refresh; upstream images point at one target.
    """

    class BootMethod(models.TextChoices):
        RPI_FIRMWARE = "rpi", _("Raspberry Pi firmware")
        UBOOT = "uboot", _("U-Boot")
        UEFI = "uefi", _("UEFI")
        BIOS = "bios", _("Legacy BIOS")
        CUSTOM = "custom", _("Custom")

    slug = models.SlugField(unique=True, help_text="e.g. rpi5, rpi4, rpi-zero2w, pc-x86_64-uefi")
    name = models.CharField(max_length=120)
    architecture = models.ForeignKey(
        Architecture,
        on_delete=models.PROTECT,
        related_name="hardware_targets",
    )
    boot_method = models.CharField(max_length=16, choices=BootMethod.choices)
    soc = models.CharField(max_length=80, blank=True, help_text="System-on-chip, e.g. BCM2712")
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["architecture__slug", "slug"]

    def __str__(self) -> str:
        return f"{self.name} ({self.architecture.slug})"


class OperatingSystem(TimestampedModel):
    """An OS family / distribution that os-bakery knows how to bake."""

    class Kind(models.TextChoices):
        RETRO = "retro", _("Retro gaming")
        DESKTOP = "desktop", _("Desktop")
        SERVER = "server", _("Server")
        EMBEDDED = "embedded", _("Embedded")
        IOT = "iot", _("IoT")

    slug = models.SlugField(unique=True, help_text="e.g. batocera, raspios, ubuntu")
    name = models.CharField(max_length=120)
    vendor = models.CharField(max_length=120, blank=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SERVER)
    homepage = models.URLField(blank=True)
    license = models.CharField(max_length=80, blank=True)
    summary = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class OSRelease(TimestampedModel):
    """A specific version/channel of an :class:`OperatingSystem`.

    Examples: Batocera 41 stable, Raspberry Pi OS Bookworm 2025-05-13,
    Ubuntu 24.04.1 LTS Server.
    """

    class Channel(models.TextChoices):
        STABLE = "stable", _("Stable")
        LTS = "lts", _("LTS")
        BETA = "beta", _("Beta")
        DEV = "dev", _("Development")
        NIGHTLY = "nightly", _("Nightly")

    operating_system = models.ForeignKey(
        OperatingSystem,
        on_delete=models.CASCADE,
        related_name="releases",
    )
    version = models.CharField(max_length=40, help_text="e.g. 41, 24.04.1, 2025-05-13")
    codename = models.CharField(max_length=80, blank=True, help_text="e.g. Bookworm, Noble")
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.STABLE)
    released_on = models.DateField(null=True, blank=True)
    end_of_life_on = models.DateField(null=True, blank=True)
    release_notes_url = models.URLField(blank=True)
    is_default = models.BooleanField(
        default=False,
        help_text="If true, recipes that don't pin a release will resolve to this one.",
    )

    class Meta:
        ordering = ["operating_system__slug", "-released_on", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["operating_system", "version", "channel"],
                name="uniq_release_per_os_version_channel",
            ),
        ]

    def __str__(self) -> str:
        suffix = f" ({self.codename})" if self.codename else ""
        return f"{self.operating_system.slug} {self.version}{suffix}"


class UpstreamImage(TimestampedModel):
    """A base image distributed by the OS vendor, for one hardware target.

    This is the *raw material* that Packer refreshes into the local base image
    cache. The Packer manifest (see :mod:`infra`) updates ``local_path``,
    ``checksum_sha256`` and ``last_synced_at`` after each successful run.
    """

    class Format(models.TextChoices):
        IMG_XZ = "img.xz", "img.xz"
        IMG_GZ = "img.gz", "img.gz"
        IMG_ZIP = "img.zip", "img.zip"
        IMG = "img", "img (raw)"
        ISO = "iso", "iso"
        QCOW2 = "qcow2", "qcow2"

    release = models.ForeignKey(OSRelease, on_delete=models.CASCADE, related_name="images")
    hardware_target = models.ForeignKey(
        HardwareTarget,
        on_delete=models.PROTECT,
        related_name="upstream_images",
    )
    variant = models.CharField(
        max_length=60,
        blank=True,
        help_text="Vendor variant, e.g. 'lite', 'desktop-full', 'server-minimal'.",
    )
    format = models.CharField(max_length=12, choices=Format.choices, default=Format.IMG_XZ)
    source_url = models.URLField(help_text="Where the upstream image lives (https://...).")
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    local_path = models.CharField(
        max_length=512,
        blank=True,
        help_text="Path under PACKER cache once mirrored locally.",
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["release", "hardware_target__slug", "variant"]
        constraints = [
            models.UniqueConstraint(
                fields=["release", "hardware_target", "variant"],
                name="uniq_upstream_image_per_release_target_variant",
            ),
        ]

    def __str__(self) -> str:
        variant = f" [{self.variant}]" if self.variant else ""
        return f"{self.release} on {self.hardware_target.slug}{variant}"

    def get_absolute_url(self) -> str:
        return reverse("admin:catalog_upstreamimage_change", args=[self.pk])

    @property
    def is_synced(self) -> bool:
        return bool(self.local_path and self.checksum_sha256)
