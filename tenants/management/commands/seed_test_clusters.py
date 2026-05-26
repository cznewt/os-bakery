"""Seed a `test` tenant with one cluster per Kind for exercising configs.

Each cluster carries a representative `parameters` tree (the cluster's share of
the effective model). Bake any recipe joined to one of these and the cluster
params merge with the device model onto the image's model.yaml.

    python manage.py seed_test_clusters
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from tenants.models import Cluster, Tenant

TENANT = {"slug": "test", "name": "Test Lab",
          "description": "Throwaway tenant for testing bake configurations."}

# (slug, name, kind, parameters, tags)
CLUSTERS = [
    ("test-arcade", "Test Arcade LAN", Cluster.Kind.BATOCERA_LAN, {
        "salt": {"master": "salt.test.lan"},
        "alloy": {"endpoint": "https://alloy.test.lan/loki/api/v1/push"},
        "batocera": {"boot_to_arcade": True,
                     "share_host": "nas.test.lan",
                     "screen_share": {"enabled": True}},
        "zerotier": {"network": "8056c2e21c000001"},
    }, ["test", "retro"]),
    ("test-kube", "Test Kubernetes", Cluster.Kind.KUBERNETES, {
        "salt": {"master": "salt.test.lan"},
        "linux": {"timezone": "Europe/Prague"},
        "kubernetes": {"api_endpoint": "https://kube.test.lan:6443",
                       "kubeadm_token": "abcdef.0123456789abcdef",
                       "pod_cidr": "10.244.0.0/16"},
    }, ["test", "infra"]),
    ("test-fleet", "Test Salt Fleet", Cluster.Kind.SALT_FLEET, {
        "salt": {"master": "salt.test.lan", "mine_interval": 60},
        "linux": {"timezone": "Europe/Prague",
                  "packages": ["htop", "vim", "curl"]},
    }, ["test", "infra"]),
    ("test-home", "Test Home Assistant", Cluster.Kind.HOME_ASSISTANT, {
        "mqtt": {"broker": "mqtt.test.lan", "port": 1883},
        "network": {"wifi_country": "CZ"},
        "linux": {"timezone": "Europe/Prague"},
    }, ["test", "iot"]),
    ("test-vpn", "Test VPN Mesh", Cluster.Kind.VPN_MESH, {
        "vpn": {"kind": "zerotier"},
        "zerotier": {"network": "8056c2e21c000001"},
        "dns": {"search": "test.lan", "servers": ["10.0.0.1"]},
    }, ["test", "net"]),
    ("test-esp", "Test ESPHome Network", Cluster.Kind.ESPHOME_NETWORK, {
        "wifi": {"ssid": "test-iot", "domain": ".test.lan"},
        "api": {"encryption": True},
        "ota": {"enabled": True},
    }, ["test", "iot"]),
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

        for slug, name, kind, params, tags in CLUSTERS:
            c, made = Cluster.objects.get_or_create(
                tenant=tenant, slug=slug,
                defaults={"name": name, "kind": kind,
                          "parameters": params, "tags": tags},
            )
            if not made:
                # Refresh params/tags so re-running keeps them current.
                c.name, c.kind, c.parameters, c.tags = name, kind, params, tags
                c.save(update_fields=["name", "kind", "parameters", "tags"])
            self.stdout.write(
                f"  {'created' if made else 'updated'}: {tenant.slug}/{c.slug} "
                f"({kind})"
            )
