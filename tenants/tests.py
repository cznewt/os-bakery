"""Tests for tenants.models.Node.effective_model identity keys.

Locks in the convention: ``salt.id`` / ``options.minion_id`` are the node **slug**
(full), while the **hostname** — the device's OS / WireGuard name — *and* the alloy
``instance`` label are the **short host name** (``minion_id`` = hostname-or-slug).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from catalog.models import Architecture, HardwareTarget, OperatingSystem
from recipes.models import Recipe, RecipeVersion
from tenants.models import Cluster, Node, Tenant


@pytest.fixture
def windows_node(db):
    """A node whose hostname (short) differs from its slug (full) — the case the
    salt.id = slug convention turns on (e.g. a roaming Windows laptop)."""
    owner = get_user_model().objects.create(username="owner")
    arch = Architecture.objects.create(slug="amd64", name="amd64", family="x86", bits=64)
    hw = HardwareTarget.objects.create(
        slug="pc-amd64", name="PC", architecture=arch, boot_method="uefi",
    )
    os_ = OperatingSystem.objects.create(slug="windows", name="Windows", kind="desktop")
    recipe = Recipe.objects.create(
        slug="windows-workstation", name="Win", operating_system=os_,
    )
    RecipeVersion.objects.create(
        recipe=recipe, version="1.0.0", is_current=True,
        pillar_overrides={"alloy": {"labels": {"cluster": "win"}}},
    )
    tenant = Tenant.objects.create(slug="gedu", name="GeekEdu", owner=owner)
    cluster = Cluster.objects.create(
        tenant=tenant, slug="gedu-computer-windows", name="Windows",
    )
    return Node.objects.create(
        cluster=cluster, slug="gameedu-roam-kubik-windows-laptop",
        name="kubik", hostname="kubik-windows", preset=recipe, hardware_target=hw,
    )


def test_salt_id_and_minion_id_default_to_slug(windows_node):
    model = windows_node.effective_model
    slug = "gameedu-roam-kubik-windows-laptop"
    # Salt minion id + options.minion_id are the full slug…
    assert model["salt"]["id"] == slug
    assert model["options"]["minion_id"] == slug
    # …while the OS hostname / WireGuard client name AND the alloy instance label
    # stay the short hostname (a concise, readable per-device series id).
    assert model["options"]["hostname"] == "kubik-windows"
    assert model["alloy"]["labels"]["instance"] == "kubik-windows"
    assert windows_node.minion_id == "kubik-windows"


def test_explicit_salt_id_in_params_still_wins(windows_node):
    windows_node.parameters = {"salt": {"id": "pinned-id"}}
    windows_node.save()
    assert windows_node.effective_model["salt"]["id"] == "pinned-id"
