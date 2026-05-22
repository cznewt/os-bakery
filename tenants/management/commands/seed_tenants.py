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


TENANTS: list[dict[str, Any]] = [
    {
        "slug": "gedu",
        "name": "GeekEdu",
        "description": "GeekEdu — educational labs and infrastructure tenant.",
        "clusters": [
            {
                "slug": "gedu-vpn",
                "name": "GeekEdu VPN mesh",
                "kind": Cluster.Kind.VPN_MESH,
                "parameters": {
                    "vpn": {
                        "kind": "zerotier",
                        "network_id": "",  # fill via /admin/
                        "network_name": "gedu-vpn",
                        "allow_global": False,
                        "allow_default_route": False,
                    },
                    "dns": {
                        "search_domains": ["gedu.lab"],
                    },
                },
                "notes": "ZeroTier mesh for GeekEdu labs. "
                         "Edit network_id via /admin/.",
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
                            "kind": cspec.get("kind", Cluster.Kind.GENERIC),
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
                        f"Cluster: {c.tenant.slug}/{c.slug} ({c.kind})"
                    )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created_tenants}+{updated_tenants} tenants, "
            f"{created_clusters}+{updated_clusters} clusters."
        ))
