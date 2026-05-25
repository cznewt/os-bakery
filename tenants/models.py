"""Tenant + Cluster — the multi-tenancy + shared-parameters layer.

A **Tenant** is the unit of separation: every recipe / build / artifact
belongs to (or is scoped under) one tenant. Owners can invite members;
public/global rows leave `tenant=None`.

A **Cluster** is a tenant-scoped group of devices that share configuration:
a Kubernetes cluster (kubeadm token, API endpoint), a Salt fleet (master
URL, mining schedule), a Home Assistant deployment (MQTT broker, network),
a Batocera LAN (game-share host, screen-share peers), etc. Recipes pull a
cluster's `parameters` JSON into the bake-time pillar so every device that
joins the cluster gets matching settings.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Tenant(TimestampedModel):
    """The unit of multi-tenant separation.

    Every Recipe / BuildRequest / Artifact can be (optionally) scoped to
    a Tenant. Owner + members are Django User FKs; an OAuth / SAML
    provider can later auto-create tenants on first login.
    """

    slug = models.SlugField(unique=True, max_length=80)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_tenants",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="tenants",
        blank=True,
        help_text="Users who can view + bake against this tenant's recipes.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Cluster(TimestampedModel):
    """A tenant-scoped group of devices that share pillar parameters.

    Bakes belonging to the same Cluster get its ``parameters`` merged into
    the pillar — so every minion that joins (say) the `prg-kube` cluster
    inherits the same kubeadm token / API endpoint without each Recipe
    repeating them.
    """

    class Kind(models.TextChoices):
        KUBERNETES = "kubernetes", _("Kubernetes")
        DOCKER_SWARM = "docker_swarm", _("Docker Swarm")
        SALT_FLEET = "salt_fleet", _("Salt Fleet")
        HOME_ASSISTANT = "home_assistant", _("Home Assistant")
        BATOCERA_LAN = "batocera_lan", _("Batocera LAN")
        ESPHOME_NETWORK = "esphome_network", _("ESPHome network")
        ROBOTICS_SWARM = "robotics_swarm", _("Robotics / autopilot swarm")
        VPN_MESH = "vpn_mesh", _("VPN mesh (ZeroTier / WireGuard / Tailscale)")
        GENERIC = "generic", _("Generic")

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="clusters",
    )
    slug = models.SlugField(
        max_length=80,
        help_text="Unique within the tenant — e.g. `prg-kube`, `home-iot`.",
    )
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.GENERIC)
    parameters = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Shared pillar tree merged into every bake that joins this cluster. "
            "Mirrors the recipe's `pillar_overrides` shape — keys like "
            "`kubernetes.api_endpoint`, `salt.master`, `mqtt.broker`."
        ),
    )
    tags = models.JSONField(
        default=list, blank=True,
        help_text="Free-form labels for filtering/grouping, e.g. ['prod', 'prg'].",
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["tenant__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "slug"],
                name="uniq_cluster_per_tenant",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.tenant.slug}/{self.slug}"
