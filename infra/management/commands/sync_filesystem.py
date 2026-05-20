"""Walk on-disk Packer + Salt trees and reconcile them with the DB registry.

Run this after editing templates or adding new Salt formula directories. It's
intentionally idempotent: existing rows are updated, new directories become new
rows, and rows pointing at directories that no longer exist are marked
archived (templates) or printed as warnings (formulas).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from infra.models import PackerTemplate, SaltFormula


class Command(BaseCommand):
    help = "Reconcile on-disk Packer templates and Salt formulas with the DB registry."

    def handle(self, *args, **options) -> None:
        self._sync_packer(settings.PACKER_TEMPLATES_ROOT)
        self._sync_salt(settings.SALT_STATES_ROOT)

    def _sync_packer(self, root: Path) -> None:
        if not root.exists():
            self.stderr.write(f"Packer root missing: {root}")
            return
        seen: set[str] = set()
        for hcl in root.rglob("*.pkr.hcl"):
            rel = hcl.relative_to(root)
            slug = "-".join(rel.with_suffix("").parts).replace(".pkr", "").lower()
            seen.add(slug)
            obj, created = PackerTemplate.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": " / ".join(rel.with_suffix("").parts),
                    "relative_path": str(rel),
                    # OS + hw inference left to the operator via admin.
                    "operating_system_id": PackerTemplate.objects.filter(slug=slug)
                    .values_list("operating_system_id", flat=True)
                    .first(),
                },
            )
            self.stdout.write(
                ("+ " if created else "~ ") + f"packer template {obj.slug} ({rel})"
            )
        stale = PackerTemplate.objects.exclude(slug__in=seen)
        n = stale.update(status=PackerTemplate.Status.ARCHIVED)
        if n:
            self.stdout.write(self.style.WARNING(f"archived {n} stale packer templates"))

    def _sync_salt(self, root: Path) -> None:
        if not root.exists():
            self.stderr.write(f"Salt root missing: {root}")
            return
        seen: set[str] = set()
        for init_sls in root.rglob("init.sls"):
            rel = init_sls.parent.relative_to(root)
            slug = ".".join(rel.parts)
            if not slug:
                continue
            seen.add(slug)
            obj, created = SaltFormula.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": slug,
                    "relative_path": str(rel),
                },
            )
            self.stdout.write(
                ("+ " if created else "~ ") + f"salt formula {obj.slug} ({rel})"
            )
        stale_slugs = list(SaltFormula.objects.exclude(slug__in=seen).values_list("slug", flat=True))
        if stale_slugs:
            self.stdout.write(
                self.style.WARNING(
                    f"salt formulas no longer on disk: {', '.join(stale_slugs)}"
                )
            )
