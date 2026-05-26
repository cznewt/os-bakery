"""Seed a `test` tenant with one cluster per Kind for exercising configs.

Each cluster carries a representative `parameters` tree (the cluster's share of
the effective model). Bake any recipe joined to one of these and the cluster
params merge with the device model onto the image's model.yaml.

    python manage.py seed_test_clusters
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from catalog.models import HardwareTarget
from recipes.models import Recipe
from tenants.models import Cluster, Node, Tenant

TENANT = {"slug": "test", "name": "Test Lab",
          "description": "Throwaway tenant for testing bake configurations."}

# (slug, name, parameters, tags)
CLUSTERS = [
    ("test-arcade", "Test Arcade LAN", {
        "salt": {"master": "salt.test.lan"},
        "alloy": {"endpoint": "https://alloy.test.lan/loki/api/v1/push"},
        "batocera": {"boot_to_arcade": True,
                     "share_host": "nas.test.lan",
                     "screen_share": {"enabled": True}},
        "zerotier": {"network": "8056c2e21c000001"},
    }, ["test", "retro"]),
    ("test-kube", "Test Kubernetes", {
        "salt": {"master": "salt.test.lan"},
        "linux": {"timezone": "Europe/Prague"},
        "kubernetes": {"api_endpoint": "https://kube.test.lan:6443",
                       "kubeadm_token": "abcdef.0123456789abcdef",
                       "pod_cidr": "10.244.0.0/16"},
    }, ["test", "infra"]),
    ("test-fleet", "Test Salt Fleet", {
        "salt": {"master": "salt.test.lan", "mine_interval": 60},
        "linux": {"timezone": "Europe/Prague",
                  "packages": ["htop", "vim", "curl"]},
    }, ["test", "infra"]),
    ("test-home", "Test Home Assistant", {
        "mqtt": {"broker": "mqtt.test.lan", "port": 1883},
        "network": {"wifi_country": "CZ"},
        "linux": {"timezone": "Europe/Prague"},
    }, ["test", "iot"]),
    ("test-vpn", "Test VPN Mesh", {
        "vpn": {"kind": "zerotier"},
        "zerotier": {"network": "8056c2e21c000001"},
        "dns": {"search": "test.lan", "servers": ["10.0.0.1"]},
    }, ["test", "net"]),
    ("test-esp", "Test ESPHome Network", {
        "wifi": {"ssid": "test-iot", "domain": ".test.lan"},
        "api": {"encryption": True},
        "ota": {"enabled": True},
    }, ["test", "iot"]),
]

# (cluster_slug, node_slug, name, preset_slug, target_slug, hostname, params, tags)
NODES = [
    ("test-arcade", "cabinet-01", "Arcade Cabinet 01", "batocera-arcade",
     "pc-amd64", "cabinet-01",
     {"batocera": {"boot_to_arcade": True, "controllers": {"players": 2}}},
     ["test", "cabinet"]),
    ("test-arcade", "handheld-01", "Handheld 01", "batocera-handheld",
     "loki-zero", "handheld-01",
     {"batocera": {"power": {"suspend_minutes": 5}}}, ["test", "handheld"]),
]


class Command(BaseCommand):
    help = "Create a `test` tenant with one cluster per kind."

    def handle(self, *args, **opts):
        User = get_user_model()
        owner = (User.objects.filter(is_superuser=True).order_by("id").first()
                 or User.objects.order_by("id").first())
        if owner is None:
            self.stderr.write("No users exist — create a superuser first.")
            return

        tenant, created = Tenant.objects.get_or_create(
            slug=TENANT["slug"],
            defaults={"name": TENANT["name"],
                      "description": TENANT["description"], "owner": owner},
        )
        self.stdout.write(f"{'created' if created else 'exists'}: tenant {tenant.slug}")

        for slug, name, params, tags in CLUSTERS:
            c, made = Cluster.objects.get_or_create(
                tenant=tenant, slug=slug,
                defaults={"name": name, "parameters": params, "tags": tags},
            )
            if not made:
                # Refresh params/tags so re-running keeps them current.
                c.name, c.parameters, c.tags = name, params, tags
                c.save(update_fields=["name", "parameters", "tags"])
            self.stdout.write(
                f"  {'created' if made else 'updated'}: {tenant.slug}/{c.slug}"
            )

        # Nodes — the units we bake images onto.
        for (cl_slug, slug, name, preset_slug, target_slug, hostname,
             params, tags) in NODES:
            cluster = Cluster.objects.filter(tenant=tenant, slug=cl_slug).first()
            preset = Recipe.objects.filter(slug=preset_slug).first()
            target = HardwareTarget.objects.filter(slug=target_slug).first()
            if not (cluster and preset and target):
                self.stdout.write(
                    f"  skip node {slug}: missing "
                    f"{'cluster' if not cluster else ''}"
                    f"{'preset' if not preset else ''}"
                    f"{'target' if not target else ''}"
                )
                continue
            n, made = Node.objects.get_or_create(
                cluster=cluster, slug=slug,
                defaults={"name": name, "hostname": hostname, "preset": preset,
                          "hardware_target": target, "parameters": params,
                          "tags": tags},
            )
            if not made:
                n.name, n.hostname, n.preset, n.hardware_target = (
                    name, hostname, preset, target)
                n.parameters, n.tags = params, tags
                n.save()
            self.stdout.write(
                f"  {'created' if made else 'updated'}: node "
                f"{tenant.slug}/{cl_slug}/{slug} ({preset_slug} on {target_slug})"
            )
