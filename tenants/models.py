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


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base``.

    Nested dicts merge; lists union (base first, then new override items) so a
    node's list values add to the cluster's baseline; scalars override. Mirrors
    builds.orchestrator._deep_merge.
    """
    result = dict(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        elif isinstance(existing, list) and isinstance(value, list):
            merged = list(existing)
            for item in value:
                if item not in merged:
                    merged.append(item)
            result[key] = merged
        else:
            result[key] = value
    return result


class Node(TimestampedModel):
    """A managed unit we bake an image for.

    A Node is the *thing* an image is baked onto: it belongs to a Cluster,
    implements a preset (recipe = the role it plays), targets one piece of
    hardware, and carries its own ``parameters`` overrides. Its ``effective_model``
    is the joined metadata — preset defaults ⊕ device identity ⊕ cluster
    parameters ⊕ this node's parameters — i.e. exactly what gets baked onto the
    image when you bake the node.
    """

    cluster = models.ForeignKey(
        Cluster,
        on_delete=models.CASCADE,
        related_name="nodes",
        help_text="The cluster this node joins; its parameters merge in.",
    )
    slug = models.SlugField(
        max_length=80,
        help_text="Unique within the cluster — e.g. `cabinet-01`, `kube-master`.",
    )
    name = models.CharField(max_length=120)
    hostname = models.CharField(
        max_length=120, blank=True,
        help_text="Hostname / salt minion id baked in. Defaults to the slug.",
    )
    preset = models.ForeignKey(
        "recipes.Recipe",
        on_delete=models.PROTECT,
        related_name="nodes",
        help_text="The preset (recipe / role) this node implements.",
    )
    hardware_target = models.ForeignKey(
        "catalog.HardwareTarget",
        on_delete=models.PROTECT,
        related_name="nodes",
        help_text="The hardware we bake the image for.",
    )
    upstream_image = models.ForeignKey(
        "catalog.UpstreamImage",
        on_delete=models.SET_NULL,
        related_name="nodes",
        null=True, blank=True,
        help_text="Optional pinned base image; otherwise resolved from the "
                  "preset's release + this node's hardware target at bake time.",
    )
    parameters = models.JSONField(
        default=dict, blank=True,
        help_text="Node-specific pillar overrides — the most specific layer, "
                  "winning over the cluster's shared parameters.",
    )
    tags = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["cluster__tenant__name", "cluster__slug", "slug"]
        constraints = [
            models.UniqueConstraint(
                fields=["cluster", "slug"],
                name="uniq_node_per_cluster",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.cluster.tenant.slug}/{self.cluster.slug}/{self.slug}"

    @property
    def tenant(self):
        return self.cluster.tenant

    @property
    def minion_id(self) -> str:
        return self.hostname or self.slug

    @property
    def effective_model(self) -> dict:
        """Joined metadata for the preset this node implements.

        preset defaults ⊕ device identity ⊕ cluster.parameters ⊕ node.parameters
        ⊕ node identity. This is the design-time view of what a bake produces.
        """
        rv = (self.preset.versions.filter(is_current=True).first()
              or self.preset.versions.order_by("-created_at").first())
        ht = self.hardware_target
        arch = getattr(ht, "architecture", None)
        model: dict = {}
        model = _deep_merge(model, (rv.pillar_overrides if rv else {}) or {})
        model = _deep_merge(model, {"device": {
            "target": ht.slug, "model": ht.name, "soc": ht.soc or None,
            "arch": getattr(arch, "slug", None), "boot_method": ht.boot_method,
        }})
        model = _deep_merge(model, self.cluster.parameters or {})
        model = _deep_merge(model, self.parameters or {})
        model = _deep_merge(model, {"options": {
            "hostname": self.minion_id, "minion_id": self.minion_id,
        }})
        model = _deep_merge(model, {"osbakery": {
            "node": f"{self.cluster.tenant.slug}/{self.cluster.slug}/{self.slug}",
            "cluster": f"{self.cluster.tenant.slug}/{self.cluster.slug}",
            "preset": self.preset.slug,
        }})
        return model
