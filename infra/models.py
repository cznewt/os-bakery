"""Registries that point the app at on-disk Packer templates and Salt formulas.

These rows are the audit trail for what *can* run: the directory layout on
disk is the source of truth, but Django keeps a registry so the admin can show
last-run times, link templates to which UpstreamImage they refresh, and link
Salt states to which recipes consume them.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from catalog.models import HardwareTarget, OperatingSystem, OSRelease, UpstreamImage
from recipes.models import Recipe


class PackerTemplate(models.Model):
    """A Packer HCL template that refreshes one or more :class:`UpstreamImage` rows."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        DRAFT = "draft", _("Draft")
        ARCHIVED = "archived", _("Archived")

    slug = models.SlugField(unique=True, max_length=80)
    name = models.CharField(max_length=120)
    relative_path = models.CharField(
        max_length=240,
        help_text=(
            "Path relative to PACKER_TEMPLATES_ROOT (e.g. 'batocera/rpi5/template.pkr.hcl')."
        ),
    )
    operating_system = models.ForeignKey(
        OperatingSystem,
        on_delete=models.PROTECT,
        related_name="packer_templates",
    )
    hardware_target = models.ForeignKey(
        HardwareTarget,
        on_delete=models.PROTECT,
        related_name="packer_templates",
        null=True,
        blank=True,
    )
    pinned_release = models.ForeignKey(
        OSRelease,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="packer_templates",
    )
    produces = models.ManyToManyField(
        UpstreamImage,
        related_name="produced_by",
        blank=True,
        help_text="UpstreamImage rows this template keeps fresh.",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_run_log = models.TextField(blank=True)

    class Meta:
        ordering = ["operating_system__slug", "slug"]

    def __str__(self) -> str:
        return self.name


class SaltFormula(models.Model):
    """A Salt state directory under ``salt/states/``.

    Recipes reference these by ID through ``RecipeVersion.salt_states``. The
    M2M back-reference here is for discoverability in the admin.
    """

    slug = models.SlugField(unique=True, max_length=80)
    name = models.CharField(max_length=120)
    relative_path = models.CharField(
        max_length=240,
        help_text="Path relative to SALT_STATES_ROOT (e.g. 'batocera/arcade').",
    )
    description = models.TextField(blank=True)
    operating_systems = models.ManyToManyField(
        OperatingSystem,
        related_name="salt_formulas",
        blank=True,
        help_text="OSes this formula is known to work against.",
    )
    used_by = models.ManyToManyField(
        Recipe,
        related_name="formulas",
        blank=True,
    )
    requires = models.JSONField(
        default=list,
        blank=True,
        help_text="List of formula slugs this one depends on (informational).",
    )
    is_internal = models.BooleanField(
        default=False,
        help_text="Internal helper formulas (not exposed to users in the recipe builder).",
    )

    class Meta:
        ordering = ["slug"]

    def __str__(self) -> str:
        return self.name
