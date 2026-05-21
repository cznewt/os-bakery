"""Seed a starter set of role-template Recipes.

Each row corresponds to a "I want one of these images" use case — Batocera
for handheld / arcade / notebook deployments, Ubuntu for desktop / Docker /
Kubernetes roles. Idempotent: re-running adds nothing, refreshes nothing.
Use ``manage.py seed_recipes --reset`` to wipe the table first.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import HardwareTarget, OperatingSystem
from recipes.models import Recipe, RecipeOption, RecipeVersion


RECIPES: list[dict[str, Any]] = [
    {
        "slug": "batocera-handheld",
        "name": "Batocera · Handheld",
        "summary": "Retro gaming preset for Anbernic / Retroid handhelds — "
                   "boot into EmulationStation, language and keyboard configured.",
        "os_slug": "batocera",
        "hardware_slugs": ["rg552", "rg353p", "rg353ps", "rg353v", "rg353vs",
                           "rg503", "loki-zero", "flip-2", "pocket-5"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "batocera.base"],
        "pillar_overrides": {"batocera": {"boot_to_arcade": False},
                             "role": "batocera-handheld"},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "handheld-1", "sort_order": 10},
            {"key": "language", "label": "System language", "kind": "choice",
             "default": "en_US", "sort_order": 20,
             "choices": [
                 {"value": "en_US", "label": "English (US)"},
                 {"value": "cs_CZ", "label": "Czech"},
                 {"value": "de_DE", "label": "German"},
                 {"value": "fr_FR", "label": "French"},
             ]},
            {"key": "wifi_ssid", "label": "Wi-Fi SSID",
             "help_text": "Optional — leave blank for offline use.",
             "kind": "string", "sort_order": 30},
            {"key": "wifi_psk", "label": "Wi-Fi password",
             "help_text": "Required if SSID is set.",
             "kind": "secret", "sort_order": 40},
        ],
    },
    {
        "slug": "batocera-arcade",
        "name": "Batocera · Arcade cabinet",
        "summary": "Boots straight into the game launcher; lockdown UI, "
                   "family-friendly defaults, attract mode.",
        "os_slug": "batocera",
        "hardware_slugs": ["pc-amd64", "rpi4", "rpi5"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "batocera.base", "batocera.arcade"],
        "pillar_overrides": {"batocera": {"boot_to_arcade": True},
                             "role": "batocera-arcade"},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "arcade-1", "sort_order": 10},
            {"key": "cabinet_name", "label": "Cabinet display name",
             "help_text": "Shown on the splash screen.",
             "kind": "string", "sort_order": 20},
            {"key": "wifi_ssid", "label": "Wi-Fi SSID", "kind": "string",
             "sort_order": 30},
            {"key": "wifi_psk", "label": "Wi-Fi password", "kind": "secret",
             "sort_order": 40},
        ],
    },
    {
        "slug": "batocera-notebook",
        "name": "Batocera · Notebook",
        "summary": "Laptop-friendly Batocera — sleep on lid close, brightness "
                   "keys, hibernate on low battery.",
        "os_slug": "batocera",
        "hardware_slugs": ["pc-amd64"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "batocera.base", "batocera.minimal"],
        "pillar_overrides": {"batocera": {"power": {"sleep_on_lid": True}},
                             "role": "batocera-notebook"},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "notebook-1", "sort_order": 10},
            {"key": "user_name", "label": "Local user", "kind": "string",
             "default": "batocera", "sort_order": 20},
            {"key": "wifi_ssid", "label": "Wi-Fi SSID", "kind": "string",
             "sort_order": 30},
            {"key": "wifi_psk", "label": "Wi-Fi password", "kind": "secret",
             "sort_order": 40},
        ],
    },
    {
        "slug": "ubuntu-desktop",
        "name": "Ubuntu · Desktop",
        "summary": "Ubuntu desktop image — GNOME preconfigured, common dev "
                   "tools, sane defaults.",
        "os_slug": "ubuntu",
        "hardware_slugs": ["pc-amd64", "rpi4", "rpi5"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "base.users", "ubuntu.base"],
        "pillar_overrides": {"variant": "desktop", "role": "ubuntu-desktop"},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "ubuntu-1", "sort_order": 10},
            {"key": "user_name", "label": "Username", "kind": "string",
             "required": True, "default": "ubuntu", "sort_order": 20},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "help_text": "One key per line; populated into "
                          "~/.ssh/authorized_keys at first boot.",
             "kind": "ssh_key", "sort_order": 30},
            {"key": "wifi_ssid", "label": "Wi-Fi SSID", "kind": "string",
             "sort_order": 40},
            {"key": "wifi_psk", "label": "Wi-Fi password", "kind": "secret",
             "sort_order": 50},
        ],
    },
    {
        "slug": "ubuntu-docker",
        "name": "Ubuntu · Docker host",
        "summary": "Headless Ubuntu Server with Docker engine + compose "
                   "preinstalled. Joins the fleet as a `*-docker-*` role.",
        "os_slug": "ubuntu",
        "hardware_slugs": ["pc-amd64", "rpi4", "rpi5", "generic-arm64",
                           "vm-qemu", "vm-hyperv", "vm-virtualbox"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "base.users", "base.hardening",
                        "ubuntu.server"],
        "pillar_overrides": {"variant": "server", "role": "ubuntu-docker",
                             "fleet_role": "docker"},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "docker-1", "sort_order": 10},
            {"key": "user_name", "label": "Admin user", "kind": "string",
             "required": True, "default": "ops", "sort_order": 20},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "help_text": "Required — headless image, SSH is the only entry "
                          "point.",
             "kind": "ssh_key", "required": True, "sort_order": 30},
            {"key": "salt_master", "label": "Salt master (optional)",
             "help_text": "If set, salt-minion is installed and configured "
                          "to talk to this master so the fleet `*-docker-*` "
                          "role state is applied on first contact.",
             "kind": "string", "sort_order": 40},
        ],
    },
    {
        "slug": "ubuntu-kube",
        "name": "Ubuntu · Kubernetes node",
        "summary": "Ubuntu Server with kubeadm + cri-o + zerotier; ready to "
                   "join an existing control plane.",
        "os_slug": "ubuntu",
        "hardware_slugs": ["pc-amd64", "rpi4", "rpi5", "generic-arm64",
                           "vm-qemu"],
        "version": "1.0.0",
        "salt_states": ["base.locale", "base.users", "base.hardening",
                        "ubuntu.server", "ubuntu.k3s"],
        "pillar_overrides": {"variant": "server", "role": "ubuntu-kube",
                             "fleet_role": "kube"},
        "options": [
            {"key": "hostname", "label": "Hostname", "kind": "string",
             "required": True, "default": "kube-1", "sort_order": 10},
            {"key": "user_name", "label": "Admin user", "kind": "string",
             "required": True, "default": "ops", "sort_order": 20},
            {"key": "ssh_authorized_keys", "label": "SSH authorized keys",
             "kind": "ssh_key", "required": True, "sort_order": 30},
            {"key": "kube_role", "label": "Cluster role", "kind": "choice",
             "default": "worker", "sort_order": 40,
             "choices": [
                 {"value": "master", "label": "Control-plane (master)"},
                 {"value": "worker", "label": "Worker"},
             ]},
            {"key": "kube_api_endpoint", "label": "API server endpoint",
             "help_text": "e.g. https://10.0.0.10:6443 (workers only).",
             "kind": "string", "sort_order": 50},
            {"key": "kube_join_token", "label": "kubeadm join token",
             "help_text": "From `kubeadm token create` on the master "
                          "(workers only).",
             "kind": "secret", "sort_order": 60},
        ],
    },
]


class Command(BaseCommand):
    help = "Seed the recipes table with the starter role templates."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--reset", action="store_true",
            help="Delete and recreate every recipe in the seed list "
                 "(also wipes RecipeVersions / RecipeOptions for them).",
        )

    def handle(self, *args, reset: bool = False, **options) -> None:
        report = {"recipes": 0, "versions": 0, "options": 0,
                  "recipes+": 0, "versions+": 0, "options+": 0}

        with transaction.atomic():
            if reset:
                Recipe.objects.filter(
                    slug__in=[r["slug"] for r in RECIPES]
                ).delete()

            for spec in RECIPES:
                os_ = OperatingSystem.objects.get(slug=spec["os_slug"])
                recipe, created = Recipe.objects.get_or_create(
                    slug=spec["slug"],
                    defaults=dict(
                        name=spec["name"],
                        summary=spec["summary"],
                        operating_system=os_,
                        status=Recipe.Status.ACTIVE,
                        visibility=Recipe.Visibility.PUBLIC,
                    ),
                )
                report["recipes"] += 1
                report["recipes+"] += int(created)
                self.stdout.write(
                    f"  [{'created' if created else 'exists '}] "
                    f"Recipe: {recipe.slug}"
                )

                # Make sure the supported hardware list matches the seed.
                targets = HardwareTarget.objects.filter(
                    slug__in=spec["hardware_slugs"]
                )
                recipe.supported_hardware.set(targets)

                version, v_created = RecipeVersion.objects.get_or_create(
                    recipe=recipe, version=spec["version"],
                    defaults=dict(
                        is_current=True,
                        salt_states=spec["salt_states"],
                        pillar_overrides=spec["pillar_overrides"],
                    ),
                )
                report["versions"] += 1
                report["versions+"] += int(v_created)

                for opt_spec in spec["options"]:
                    opt, o_created = RecipeOption.objects.get_or_create(
                        recipe=recipe, key=opt_spec["key"],
                        defaults=dict(
                            label=opt_spec["label"],
                            help_text=opt_spec.get("help_text", ""),
                            kind=opt_spec.get("kind", "string"),
                            default=opt_spec.get("default"),
                            choices=opt_spec.get("choices", []),
                            required=opt_spec.get("required", False),
                            sort_order=opt_spec.get("sort_order", 0),
                        ),
                    )
                    report["options"] += 1
                    report["options+"] += int(o_created)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded: {report['recipes']} recipes ({report['recipes+']} new), "
            f"{report['versions']} versions ({report['versions+']} new), "
            f"{report['options']} options ({report['options+']} new)."
        ))
