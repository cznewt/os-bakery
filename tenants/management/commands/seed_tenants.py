"""Seed the starter Tenant + Cluster rows.

Idempotent — uses update_or_create so editing the seed in-place and
re-running this command also refreshes the existing rows. Survives
`make compose-reset` because the compose web entrypoint runs it on
boot (alongside seed_catalog + seed_recipes).
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from tenants.models import Cluster, Tenant


# Mirrors gedu's Kapitan salt model — the `deploy-*` pillar fragments
# from /home/newt/work/models/gedu-sites-model/inventory/targets/gedu-prg-infra/gedu-prg-infra-salt.yml.
# Sensitive values (Wi-Fi passwords, batocera repo creds, SSH keys) are
# inline for dev convenience; production should layer them via a secret
# store, not via this seed.

_GEDU_SSH_KEYS = [
    # newt
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC3odU+3V2uDA2ptAFL9hrJRPNEEdAyz"
    "tWOZFQ5Oyd9oerTGOU3p4xmrgWWjfKFKbYGhiiIUcYAol5PkTfKukGEkkjCHYA1t023s"
    "oCaaAj85wCZCnw2zQNAziwxTYmAzTqgxiSvtZNMMrtJvFHRIRDzJ3M1lV0prWNWkMM1/"
    "3FAd4W49y6VT3fkMCo8uqG7CfGdgR2DgBCxf9KaNPfW5eDEPOgmE5lK8tVSEI6T+Cg7h"
    "bcTf4lFYnlFBnlQgp/0JstsM4Vbwb4B34LOpOsf2S8rrWk2xQMjwaMHXkc2s/E8iW3F5"
    "nVFuyEXYISFQIiAHw8dzC6CHgLcyHUVWwznKawZ newt@gedu",
    # majklk
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDFEv5sUV8eQQfQwJQcn1hVgUwNCOMx"
    "6Oc7Zc+Jvhd3Ap+HdDAO5FnDjQIR8g/mHSlPRh2dkbtPlq6/r5huNxH/K18N1t2HGste"
    "q+gPDorKOKDcHDPaJE3BHtcMCFz6xY+3niNX65/4Th9YjMiZjzaO4s8deE+nDldoAneF"
    "BS7Aq+wEn/Y1N66u2bQhEy5WhwwGvUMkq/zRZw3+DdDYx7gBUwikhkm+6RxGMhyzIEau"
    "GXzXxqYu5B9S+fT9yUg4zU1W75MzYjNTGvJ7I89PlgSWygaA1RqJDpdvrbsJBJbtZJhX"
    "vAFE79MFgTvnNrMJjbrl/OM9kvve3/uWDZtwscOj majklk@gedu",
]

_GEDU_BATOCERA_REPOS = [
    {"name": "arcade-machine",
     "source": "https://batocera:XGFy93LhJUGNGD0@private-games.batocera.gameedu.eu/arcade-machine/"},
    {"name": "classic-portable-console",
     "source": "https://batocera:XGFy93LhJUGNGD0@private-games.batocera.gameedu.eu/classic-portable-console/"},
    {"name": "modern-portable-console",
     "source": "https://batocera:XGFy93LhJUGNGD0@private-games.batocera.gameedu.eu/modern-portable-console/"},
    {"name": "classic-home-console",
     "source": "https://batocera:XGFy93LhJUGNGD0@private-games.batocera.gameedu.eu/classic-home-console/"},
    {"name": "modern-home-console",
     "source": "https://batocera:XGFy93LhJUGNGD0@private-games.batocera.gameedu.eu/modern-home-console/"},
    {"name": "home-computer",
     "source": "https://batocera:XGFy93LhJUGNGD0@private-games.batocera.gameedu.eu/home-computer/"},
    {"name": "modern-games",
     "source": "https://batocera:XGFy93LhJUGNGD0@private-games.batocera.gameedu.eu/modern-games/"},
    {"name": "ports",
     "source": "https://batocera:XGFy93LhJUGNGD0@private-games.batocera.gameedu.eu/ports/"},
    {"name": "utils",
     "source": "https://batocera:XGFy93LhJUGNGD0@private-utils.batocera.gameedu.eu/"},
]

_GEDU_BATOCERA_BASE_PACKAGES = [
    {"name": "misc-es-theme-gedu"},
    {"name": "misc-batocera-splash-gedu"},
    {"name": "misc-bios-batocera-42"},
    {"name": "misc-system-wine-10-19"},
    {"name": "ports-super-tux-kart"},
]

# Virtual roms — slim "join the server" tiles over an installed base package
# (batocera.virtual_roms formula; see os-bakery docs/virtual-roms.md). Attach to
# clusters that ship the matching base package (here ports-super-tux-kart). The
# STK server runs host-networked on bravo, reachable at 10.13.13.2:2759 over the
# WireGuard mesh; `connect` defaults to --connect-now={server} for SuperTuxKart.
_GEDU_BATOCERA_VIRTUAL_ROMS = [
    {"base": "ports-super-tux-kart",
     "name": "SuperTuxKart Online",
     "server": "10.13.13.2:2759"},
]


TENANTS: list[dict[str, Any]] = [
    {
        "slug": "gedu",
        "name": "GeekEdu",
        "description": "GeekEdu — educational labs and infrastructure tenant.",
        "clusters": [
            # ---- VPN meshes ----------------------------------------
            {
                "slug": "gedu-vpn",
                "name": "GeekEdu PRG infrastructure mesh",
                "notes": "ZeroTier infra mesh for Prague datacenter — "
                         "`a57fdfffb0c77a31 craftama-infrastructure`. "
                         "Synced from deploy-gedu-prg in "
                         "gedu-sites-model/.../gedu-prg-infra-salt.yml.",
                "parameters": {
                    "vpn": {
                        "kind": "zerotier",
                        "network_id": "a57fdfffb0c77a31",
                        "network_name": "craftama-infrastructure",
                    },
                    "zerotier": {
                        "networks": [
                            {"id": "a57fdfffb0c77a31",
                             "name": "craftama-infrastructure"},
                        ],
                    },
                    "salt": {"master": {"host": "10.50.61.17"}},
                    "linux": {"domain": "prg.gedu"},
                    "dns": {"search_domains": ["prg.gedu", "gedu.lab"]},
                },
            },
            {
                "slug": "gedu-roam",
                "name": "GeekEdu roaming mesh",
                "notes": "ZeroTier mesh for laptops + handhelds — "
                         "`a57fdfffb03ef7e9 nxlabs-geekedu`. "
                         "Synced from deploy-gedu-roam.",
                "parameters": {
                    "vpn": {
                        "kind": "zerotier",
                        "network_id": "a57fdfffb03ef7e9",
                        "network_name": "nxlabs-geekedu",
                    },
                    "zerotier": {
                        "networks": [
                            {"id": "a57fdfffb03ef7e9",
                             "name": "nxlabs-geekedu"},
                        ],
                    },
                },
            },
            # ---- Kubernetes datacenter ------------------------------
            {
                "slug": "gedu-prg-kube",
                "name": "GeekEdu Prague Kubernetes",
                "notes": "Newt-Prague k8s 1.34 + flannel. Synced from "
                         "deploy-gedu-prg.",
                "parameters": {
                    "kubernetes": {
                        "api": {
                            "host": "10.70.0.111",
                            "advertise": {"address": "10.70.0.111"},
                        },
                        "version": "1.34.4",
                        "network": {"kind": "flannel"},
                    },
                    "linux": {"domain": "prg.gedu"},
                    "salt": {"master": {"host": "10.50.61.17"}},
                },
            },
            # ---- Batocera arcade fleet ------------------------------
            {
                "slug": "gedu-arcade",
                "name": "GeekEdu arcade fleet",
                "notes": "Arcade + roaming Batocera devices for GeekEdu "
                         "classrooms. Synced from deploy-gedu (batocera "
                         "repos + Wi-Fi + SSH keys) + alloy observability.",
                "parameters": {
                    "salt": {"master": {"host": "salt.vpn.geekedu.eu"}},
                    "batocera": {
                        "domain": "vpn.geekedu.eu",
                        "wifi_networks": [
                            {"ssid": "robotice-5g",
                             "key": "mattonijesteje"},
                            {"ssid": "gedu",
                             "key": "scholaludus"},
                            {"ssid": "robotice",
                             "key": "mattonijesteje"},
                        ],
                        "ssh_keys": _GEDU_SSH_KEYS,
                        "repositories": _GEDU_BATOCERA_REPOS,
                        "base_packages": _GEDU_BATOCERA_BASE_PACKAGES,
                        "virtual_roms": _GEDU_BATOCERA_VIRTUAL_ROMS,
                    },
                    "alloy": {
                        "labels": {"cluster": "gedu-prg"},
                        "metrics_destination": {
                            "url": "http://10.50.61.11:19090/api/v1/metrics/write",
                            "tenant": "newt",
                        },
                        "logs_destination": {
                            "url": "http://10.50.61.11:13001/loki/api/v1/push",
                            "tenant": "newt",
                        },
                    },
                },
            },
        ],
    },
]


class Command(BaseCommand):
    help = "Seed starter Tenant + Cluster rows (idempotent)."

    def handle(self, *args, **options) -> None:
        User = get_user_model()
        owner = (User.objects.filter(is_superuser=True).first()
                 or User.objects.first())
        if owner is None:
            self.stdout.write(self.style.WARNING(
                "No User in the database — skipping tenant seed. "
                "Create a superuser first (manage.py createsuperuser)."
            ))
            return

        created_tenants, updated_tenants = 0, 0
        created_clusters, updated_clusters = 0, 0

        with transaction.atomic():
            for spec in TENANTS:
                clusters = spec.pop("clusters", [])
                t, t_created = Tenant.objects.update_or_create(
                    slug=spec["slug"],
                    defaults={
                        "name": spec["name"],
                        "description": spec.get("description", ""),
                        "is_active": spec.get("is_active", True),
                        "owner": owner,
                    },
                )
                if t_created:
                    created_tenants += 1
                else:
                    updated_tenants += 1
                self.stdout.write(
                    f"  [{'created' if t_created else 'updated'}] "
                    f"Tenant: {t.slug}"
                )

                for cspec in clusters:
                    c, c_created = Cluster.objects.update_or_create(
                        tenant=t, slug=cspec["slug"],
                        defaults={
                            "name": cspec["name"],
                            "parameters": cspec.get("parameters", {}),
                            "notes": cspec.get("notes", ""),
                            "is_active": cspec.get("is_active", True),
                        },
                    )
                    if c_created:
                        created_clusters += 1
                    else:
                        updated_clusters += 1
                    self.stdout.write(
                        f"    [{'created' if c_created else 'updated'}] "
                        f"Cluster: {c.tenant.slug}/{c.slug}"
                    )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created_tenants}+{updated_tenants} tenants, "
            f"{created_clusters}+{updated_clusters} clusters."
        ))
