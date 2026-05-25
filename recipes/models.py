"""Recipes describe **how** to customize a base image for a specific end user.

A recipe is the customer-facing unit. It picks an :class:`catalog.OperatingSystem`,
declares which :class:`catalog.HardwareTarget` it supports, and references a set
of Salt states (top-file fragments + pillar overrides) that bake the
customizations into the image.

Recipes are versioned: when you change the Salt states or pillar, you bump a
:class:`RecipeVersion`. Builds always pin to a specific RecipeVersion so the
artifact is reproducible.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from catalog.models import HardwareTarget, OperatingSystem, OSRelease


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Recipe(TimestampedModel):
    """A named customization profile.

    Recipes can be private (only the owner sees them), internal (team), or
    public (listed on the marketplace). All builds are scoped to a single
    :class:`RecipeVersion`.
    """

    class Visibility(models.TextChoices):
        PRIVATE = "private", _("Private")
        INTERNAL = "internal", _("Internal")
        PUBLIC = "public", _("Public")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ACTIVE = "active", _("Active")
        DEPRECATED = "deprecated", _("Deprecated")

    slug = models.SlugField(unique=True, max_length=80)
    name = models.CharField(max_length=120)
    summary = models.CharField(max_length=240, blank=True)
    description = models.TextField(blank=True, help_text="Markdown supported.")
    operating_system = models.ForeignKey(
        OperatingSystem,
        on_delete=models.PROTECT,
        related_name="recipes",
    )
    provisioner = models.ForeignKey(
        "catalog.Provisioner",
        on_delete=models.SET_NULL,
        related_name="recipes",
        null=True,
        blank=True,
        help_text="How this recipe customizes the image (Salt by default). "
                  "Falls back to Salt when unset.",
    )
    pinned_release = models.ForeignKey(
        OSRelease,
        on_delete=models.SET_NULL,
        related_name="recipes",
        null=True,
        blank=True,
        help_text="If set, builds always use this release; otherwise the OS default is used.",
    )
    supported_hardware = models.ManyToManyField(
        HardwareTarget,
        related_name="recipes",
        help_text="Hardware targets that this recipe is known to produce working images for.",
    )
    visibility = models.CharField(
        max_length=12,
        choices=Visibility.choices,
        default=Visibility.PRIVATE,
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_recipes",
        null=True,
        blank=True,
    )
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        related_name="recipes",
        null=True,
        blank=True,
        help_text="Tenant that owns this recipe. Leave blank for global recipes.",
    )
    icon = models.CharField(max_length=80, blank=True, help_text="UI icon hint.")
    tags = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name

    @property
    def current_version(self) -> RecipeVersion | None:
        return self.versions.filter(is_current=True).first()


class RecipeVersion(TimestampedModel):
    """A frozen snapshot of a recipe's Salt configuration.

    Bumping a version is how you ship updates while keeping older builds
    reproducible. Only one version per recipe is marked ``is_current`` — new
    builds default to it; users may opt into older versions.
    """

    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="versions")
    version = models.CharField(max_length=20, help_text="Semver-ish, e.g. '1.4.0'.")
    is_current = models.BooleanField(default=False)
    salt_top_yaml = models.TextField(
        blank=True,
        help_text=(
            "Optional inline `top.sls` fragment. If empty, "
            "`salt/top/{recipe.slug}.sls` is used."
        ),
    )
    salt_states = models.JSONField(
        default=list,
        blank=True,
        help_text="Ordered list of Salt state IDs to apply, e.g. ['base.hardening', 'batocera.arcade'].",
    )
    pillar_overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text="Pillar tree merged on top of the per-OS defaults at build time.",
    )
    changelog = models.TextField(blank=True)

    class Meta:
        ordering = ["recipe__slug", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipe", "version"],
                name="uniq_recipe_version",
            ),
        ]

    def __str__(self) -> str:
        suffix = "*" if self.is_current else ""
        return f"{self.recipe.slug}@{self.version}{suffix}"

    def save(self, *args, **kwargs) -> None:
        super().save(*args, **kwargs)
        if self.is_current:
            (
                RecipeVersion.objects.filter(recipe=self.recipe)
                .exclude(pk=self.pk)
                .update(is_current=False)
            )


class RecipeOption(TimestampedModel):
    """A parameter the user fills in when requesting a build of this recipe.

    Options surface in the build UI as a form. Their values flow into the
    pillar tree under the ``options`` key so Salt states can read them.
    """

    class Kind(models.TextChoices):
        STRING = "string", _("String")
        TEXT = "text", _("Multiline text")
        INTEGER = "integer", _("Integer")
        BOOLEAN = "boolean", _("Boolean")
        CHOICE = "choice", _("Single choice")
        MULTI_CHOICE = "multi_choice", _("Multiple choice")
        FILE = "file", _("File upload")
        SSH_KEY = "ssh_key", _("SSH public key")
        SECRET = "secret", _("Secret (stored encrypted)")

    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="options")
    key = models.SlugField(
        max_length=80,
        help_text="Pillar key (becomes pillar['options'][key] at build time).",
    )
    label = models.CharField(max_length=120)
    help_text = models.CharField(max_length=240, blank=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.STRING)
    default = models.JSONField(null=True, blank=True)
    choices = models.JSONField(
        default=list,
        blank=True,
        help_text="For choice/multi_choice kinds: list of {value, label} dicts.",
    )
    required = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["recipe__slug", "sort_order", "key"]
        constraints = [
            models.UniqueConstraint(fields=["recipe", "key"], name="uniq_option_per_recipe"),
        ]

    def __str__(self) -> str:
        return f"{self.recipe.slug}.{self.key}"
