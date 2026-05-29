"""Build orchestration: request → run → artifact → download token.

The lifecycle is:

1. A user (or API client) creates a :class:`BuildRequest` referencing a
   :class:`recipes.RecipeVersion`, a :class:`catalog.HardwareTarget`, and a
   set of option values.
2. ``builds.tasks.run_build`` picks it up off the ``builds`` Celery queue,
   copies the base image, mounts it loopback (or via libguestfs), runs
   ``salt-call`` against the merged pillar, repackages, computes checksums,
   and writes an :class:`Artifact`.
3. The artifact gets one or more :class:`DownloadToken` records that grant
   time-bounded, optionally usage-bounded download access.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from catalog.models import HardwareTarget, UpstreamImage
from recipes.models import RecipeVersion


def _generate_download_token() -> str:
    return secrets.token_urlsafe(32)


def strip_nul(value):
    """Recursively drop NUL (U+0000) from strings in an event payload.

    Postgres ``text``/``jsonb`` columns cannot store U+0000, yet salt-call /
    pacman output captured into a :class:`BuildEvent` sometimes contains it — so
    a build that applied successfully would still be failed by an unstorable log
    byte on INSERT. Stripping happens at the persistence boundary
    (:meth:`BuildEvent.save`) so every emit path is covered, not only the ones
    that remembered to sanitize.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {key: strip_nul(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [strip_nul(item) for item in value]
    return value


class BuildRequest(models.Model):
    """A user-submitted intent to bake one image."""

    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        PREPARING = "preparing", _("Preparing")
        BUILDING = "building", _("Building")
        FINALIZING = "finalizing", _("Finalizing")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")
        EXPIRED = "expired", _("Expired")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="build_requests",
        null=True,
        blank=True,
    )
    recipe_version = models.ForeignKey(
        RecipeVersion,
        on_delete=models.PROTECT,
        related_name="build_requests",
    )
    hardware_target = models.ForeignKey(
        HardwareTarget,
        on_delete=models.PROTECT,
        related_name="build_requests",
    )
    upstream_image = models.ForeignKey(
        UpstreamImage,
        on_delete=models.PROTECT,
        related_name="build_requests",
        help_text="Resolved base image (one upstream image per release+target).",
    )
    option_values = models.JSONField(
        default=dict,
        blank=True,
        help_text="Filled-in RecipeOption values. Validated against the recipe at submit.",
    )
    label = models.CharField(
        max_length=120,
        blank=True,
        help_text="Optional user-supplied label (e.g. hostname or customer name).",
    )
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        related_name="build_requests",
        null=True,
        blank=True,
    )
    cluster = models.ForeignKey(
        "tenants.Cluster",
        on_delete=models.SET_NULL,
        related_name="build_requests",
        null=True,
        blank=True,
        help_text=(
            "Optional Cluster the new device joins. Its `parameters` JSON "
            "merges into the pillar at bake time."
        ),
    )
    node = models.ForeignKey(
        "tenants.Node",
        on_delete=models.SET_NULL,
        related_name="build_requests",
        null=True,
        blank=True,
        help_text=(
            "Optional Node this build bakes. When set, the node's parameters "
            "merge into the effective model (winning over the cluster) and the "
            "build inherits the node's cluster + hardware target."
        ),
    )

    effective_model = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Snapshot of the merged config baked into the image: device "
            "identity (hardware model/SoC/arch) + recipe defaults + per-build "
            "options + the joined cluster's parameters. Written verbatim onto "
            "the image as model.yaml and shown on the baked-image page."
        ),
    )

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    celery_task_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-queued_at"]
        indexes = [
            models.Index(fields=["status", "queued_at"]),
        ]

    def __str__(self) -> str:
        return f"Build {self.id} :: {self.recipe_version} → {self.hardware_target.slug}"

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            self.Status.SUCCEEDED,
            self.Status.FAILED,
            self.Status.CANCELLED,
            self.Status.EXPIRED,
        }

    @property
    def duration(self) -> timedelta | None:
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return None


class BuildEvent(models.Model):
    """A timeline entry for a build (status changes, log markers, etc.)."""

    class Level(models.TextChoices):
        DEBUG = "debug", _("Debug")
        INFO = "info", _("Info")
        WARNING = "warning", _("Warning")
        ERROR = "error", _("Error")

    build = models.ForeignKey(BuildRequest, on_delete=models.CASCADE, related_name="events")
    at = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=8, choices=Level.choices, default=Level.INFO)
    phase = models.CharField(max_length=40, blank=True, help_text="e.g. 'mount', 'salt', 'pack'")
    message = models.TextField()
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["at"]
        indexes = [models.Index(fields=["build", "at"])]

    def save(self, *args, **kwargs):
        # salt-call / pacman output captured into message+data can contain NUL
        # (U+0000), which Postgres text/jsonb reject — a successful build must
        # not be failed by an unstorable log byte. Strip here so every emit path
        # (provisioner _emit helpers, raw BuildEvent.objects.create, admin) is
        # covered centrally rather than per-call-site.
        self.message = strip_nul(self.message or "")
        self.data = strip_nul(self.data if self.data is not None else {})
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"[{self.level}] {self.phase}: {self.message[:60]}"


class Artifact(models.Model):
    """A produced image file ready for download."""

    class Format(models.TextChoices):
        IMG_XZ = "img.xz", "img.xz"
        IMG_GZ = "img.gz", "img.gz"
        IMG_ZIP = "img.zip", "img.zip"
        IMG = "img", "img (raw)"
        ISO = "iso", "iso"

    build = models.OneToOneField(
        BuildRequest,
        on_delete=models.CASCADE,
        related_name="artifact",
    )
    storage_key = models.CharField(
        max_length=512,
        help_text="Path within the artifacts storage backend (local FS or S3 key).",
    )
    filename = models.CharField(max_length=200)
    format = models.CharField(max_length=12, choices=Format.choices, default=Format.IMG_XZ)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    media_type = models.CharField(max_length=80, default="application/octet-stream")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.filename} ({self.size_bytes} bytes)"

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at < timezone.now()

    @property
    def public_url(self) -> str:
        """Browser-reachable S3 URL for the artifact, if configured.

        Built from AWS_S3_PUBLIC_ENDPOINT + bucket + storage_key so the UI can
        link straight to the object in S3 instead of streaming the bytes
        through the app. Empty when no public endpoint is set (local backend);
        callers then fall back to the token download endpoint.
        """
        from django.conf import settings
        base = getattr(settings, "AWS_S3_PUBLIC_ENDPOINT", "") or ""
        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or ""
        if self.storage_key and base and bucket:
            return f"{base.rstrip('/')}/{bucket}/{self.storage_key}"
        return ""


class DownloadToken(models.Model):
    """A bearer token that grants access to an :class:`Artifact`.

    Tokens carry their own expiry and (optional) usage cap. Sharing the token
    URL is the entire authorization surface — keep them short-lived.
    """

    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="tokens")
    token = models.CharField(
        max_length=64,
        unique=True,
        default=_generate_download_token,
        editable=False,
    )
    issued_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="download_tokens",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    max_uses = models.PositiveIntegerField(default=0, help_text="0 = unlimited within TTL.")
    use_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["expires_at"])]

    def __str__(self) -> str:
        return f"token({self.artifact.filename})"

    @property
    def is_valid(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at < timezone.now():
            return False
        if self.max_uses and self.use_count >= self.max_uses:
            return False
        return True

    def register_use(self) -> None:
        self.use_count = models.F("use_count") + 1
        self.last_used_at = timezone.now()
        self.save(update_fields=["use_count", "last_used_at"])
        self.refresh_from_db(fields=["use_count"])

    def revoke(self) -> None:
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])
