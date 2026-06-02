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


class Provisioner(TimestampedModel):
    """How a recipe customizes the base image during a bake.

    The orchestrator dispatches on this: ``salt`` runs ``salt-call --local``
    (the current/default path); ``ansible`` and ``cloud-init`` are recognized
    targets for future provisioner backends. All shipped recipes are ``salt``.
    """

    class Slug(models.TextChoices):
        SALT = "salt", _("Salt")
        ANSIBLE = "ansible", _("Ansible")
        CLOUD_INIT = "cloud-init", _("Cloud-Init")

    slug = models.SlugField(unique=True, max_length=20, choices=Slug.choices)
    name = models.CharField(max_length=60)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    available_states = models.JSONField(
        default=list, blank=True,
        help_text="The units this provisioner can apply — Salt formulas/states "
                  "(e.g. 'base.locale'), Ansible roles, or cloud-init modules. "
                  "Each item: {slug, name, description}.",
    )

    class Meta:
        ordering = ["-is_default", "name"]

    def __str__(self) -> str:
        return self.name


class WorkflowStep(TimestampedModel):
    """One ordered step in a provisioner's bake workflow.

    A bake is rendered into an Argo Workflow: each step is a container image
    that receives env vars (build params + the step's own ``env``) and hands
    artifacts to the next step via S3. The default pipeline is
    fetch-base → provision → pack → push-s3; recipes inherit their
    provisioner's steps.
    """

    provisioner = models.ForeignKey(
        Provisioner, on_delete=models.CASCADE, related_name="steps",
    )
    order = models.PositiveSmallIntegerField(default=0)
    name = models.SlugField(max_length=40, help_text="e.g. fetch-base, provision, pack, push-s3")
    image = models.CharField(
        max_length=200,
        help_text="Container image the step runs, e.g. ghcr.io/cznewt/os-bakery-step-pack:latest",
    )
    command = models.JSONField(
        default=list, blank=True,
        help_text="Optional command/args override (list of strings).",
    )
    env = models.JSONField(
        default=dict, blank=True,
        help_text="Extra env vars for this step (merged over the build-wide env).",
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["provisioner", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["provisioner", "order"],
                name="uniq_step_order_per_provisioner",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provisioner.slug}[{self.order}] {self.name}"


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
    image_url = models.URLField(
        blank=True,
        help_text=(
            "Product photo (Wikipedia Commons, vendor CDN, ...). "
            "Used on the /devices/ page; falls back to a letter avatar."
        ),
    )

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
        MOBILE = "mobile", _("Mobile")

    slug = models.SlugField(unique=True, help_text="e.g. batocera, raspios, ubuntu")
    name = models.CharField(max_length=120)
    vendor = models.CharField(max_length=120, blank=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SERVER)
    homepage = models.URLField(blank=True)
    changelog_url = models.URLField(
        blank=True,
        help_text="Upstream changelog / release-notes page, linked from images.",
    )
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
    extra_targets = models.ManyToManyField(
        HardwareTarget,
        blank=True,
        related_name="shared_images",
        help_text="Additional devices that run this exact same image (beyond "
                  "the primary hardware_target) — e.g. the x86_64 build shared "
                  "by Steam Deck + Loki Zero.",
    )
    format = models.CharField(max_length=12, choices=Format.choices, default=Format.IMG_XZ)
    source_url = models.URLField(help_text="Where the upstream image lives (https://...).")
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    local_path = models.CharField(
        max_length=512,
        blank=True,
        help_text="Filesystem path on the build host when a local mirror is "
                  "in use. Legacy — prefer cache_storage_key (MinIO/S3).",
    )
    cache_storage_key = models.CharField(
        max_length=512,
        blank=True,
        help_text=(
            "Object key inside the artifacts S3 bucket where the "
            "decompressed upstream image is mirrored. Filled in by "
            "`manage.py refresh_upstream`. Preferred over local_path."
        ),
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    mirror_started_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Set when a mirror (sync) job is queued/running; cleared on "
                  "failure. While set and not yet cached, the UI shows 'syncing'.",
    )

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
        """Mirrored and ready to bake from — via the MinIO/S3 cache (preferred)
        or the legacy Packer local_path mirror."""
        return bool(self.cache_storage_key or (self.local_path and self.checksum_sha256))

    @property
    def is_cached(self) -> bool:
        """True when the decompressed image is mirrored in the artifacts store."""
        return bool(self.cache_storage_key)

    @property
    def is_syncing(self) -> bool:
        """A mirror job has been kicked off but the blob isn't cached yet."""
        return bool(self.mirror_started_at) and not self.cache_storage_key

    @property
    def public_url(self) -> str:
        """Browser-reachable S3 URL for the mirrored blob, if configured.

        Built from AWS_S3_PUBLIC_ENDPOINT + bucket + cache_storage_key so the UI
        can link straight to the object instead of streaming through the app.
        Empty when not mirrored or no public endpoint is set.
        """
        from django.conf import settings
        base = getattr(settings, "AWS_S3_PUBLIC_ENDPOINT", "") or ""
        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or ""
        if self.cache_storage_key and base and bucket:
            return f"{base.rstrip('/')}/{bucket}/{self.cache_storage_key}"
        return ""


class WireguardPeer(TimestampedModel):
    """A selectable remote WireGuard peer — the server/endpoint side a device
    dials into; the WG analogue of a ZeroTier network.

    Attaching one to a node expands at bake into ``wireguard.interfaces[].peers[]``
    in the pillar (``public_key`` + ``endpoint`` + ``allowed_ips``), while the
    node's own ``[Interface] PrivateKey`` is spliced from its
    ``tenants.WireguardIdentity`` (and that node's public key is what you
    authorize as a ``[Peer]`` on this server). ``allowed_ips`` carries the
    subnets routed through the tunnel — e.g. the kube node host LAN so host IPs
    are reachable, or ``0.0.0.0/0`` for a full tunnel.
    """

    slug = models.SlugField(unique=True, help_text="e.g. gedu-prg, newt-prg.")
    name = models.CharField(max_length=120)
    interface = models.CharField(
        max_length=32, default="wg0",
        help_text="Local WireGuard interface on the device; matches "
                  "tenants.WireguardIdentity.interface and wireguard.interfaces[].name.",
    )
    endpoint_host = models.CharField(
        max_length=255,
        help_text="Public FQDN/IP clients dial (WAN side of the UDP forward), "
                  "e.g. lab.geekedu.eu.",
    )
    endpoint_port = models.PositiveIntegerField(default=51820)
    public_key = models.TextField(
        blank=True,
        help_text="Server's WireGuard public key (the [Peer] PublicKey clients use). "
                  "Blank until the endpoint is up; read via `wg show`.",
    )
    allowed_ips = models.JSONField(
        default=list, blank=True,
        help_text='Subnets routed through the tunnel, e.g. '
                  '["10.50.61.0/24", "10.13.13.0/24"] (split) or ["0.0.0.0/0"] (full).',
    )
    persistent_keepalive = models.PositiveIntegerField(
        default=25, help_text="Seconds; keeps NAT open from behind-NAT devices. 0 = off.",
    )
    address_pool = models.CharField(
        max_length=64, blank=True,
        help_text="Overlay subnet to allocate node tunnel IPs from (CIDR), e.g. "
                  "10.13.13.0/24 — the node form pre-fills the next free address.",
    )
    dns = models.JSONField(
        default=list, blank=True, help_text="Optional DNS servers pushed for the tunnel.",
    )
    controller = models.ForeignKey(
        "tenants.Integration",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="wireguard_peers",
        help_text="Optional wg-easy controller (Integration of type wg_easy). When "
                  "set, attaching this peer to a node registers the node on the "
                  "controller (mints its keypair + tunnel IP) instead of generating "
                  "a key locally — the WireGuard analogue of ZeroTier registration.",
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"{self.slug} → {self.endpoint}"

    @property
    def endpoint(self) -> str:
        return f"{self.endpoint_host}:{self.endpoint_port}"
