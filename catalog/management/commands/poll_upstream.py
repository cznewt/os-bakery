"""Poll upstream OS vendors for new releases.

Iterates the active OperatingSystem rows, dispatches to the matching watcher
(see :mod:`catalog.upstream`), and reports anything that looks new. With
``--apply`` the command also creates the OSRelease / UpstreamImage rows.

This is a skeleton — the watcher implementations are stubs that return []
until somebody wires up the per-vendor scrapers. Running the command now
just confirms the wiring is in place.

Usage:

    python manage.py poll_upstream
    python manage.py poll_upstream --os batocera --os raspios
    python manage.py poll_upstream --apply           # also create DB rows
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from catalog.models import OperatingSystem, OSRelease, UpstreamImage, HardwareTarget
from catalog.upstream import get_watcher


class Command(BaseCommand):
    help = "Poll upstream OS vendors for new releases."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--os", action="append", dest="os_slugs",
            help="Only poll the named OS (repeatable).",
        )
        parser.add_argument(
            "--apply", action="store_true",
            help="Create OSRelease / UpstreamImage rows for new versions.",
        )

    def handle(self, *args, os_slugs=None, apply=False, **options) -> None:
        queryset = OperatingSystem.objects.filter(is_active=True)
        if os_slugs:
            queryset = queryset.filter(slug__in=os_slugs)

        seen_any = False
        for os_obj in queryset:
            watcher = get_watcher(os_obj.slug)
            if watcher is None:
                self.stdout.write(self.style.WARNING(
                    f"  {os_obj.slug}: no watcher registered, skipping."
                ))
                continue

            self.stdout.write(f"Polling {os_obj.slug} ({watcher.upstream_index_url}) …")
            candidates = watcher.latest_releases()
            if not candidates:
                self.stdout.write(f"  {os_obj.slug}: no new candidates.")
                continue

            seen_any = True
            for cand in candidates:
                exists = OSRelease.objects.filter(
                    operating_system=os_obj,
                    version=cand.version,
                    channel=cand.channel,
                ).exists()
                tag = "exists" if exists else "NEW"
                self.stdout.write(
                    f"  {os_obj.slug}: [{tag}] {cand.version}/{cand.channel}"
                    + (f" ({cand.codename})" if cand.codename else "")
                )
                if apply and not exists:
                    release = OSRelease.objects.create(
                        operating_system=os_obj,
                        version=cand.version,
                        channel=cand.channel,
                        codename=cand.codename,
                        released_on=cand.released_on,
                        release_notes_url=cand.release_notes_url,
                    )
                    for (target_slug, variant), url in cand.images.items():
                        try:
                            target = HardwareTarget.objects.get(slug=target_slug)
                        except HardwareTarget.DoesNotExist:
                            continue
                        UpstreamImage.objects.create(
                            release=release,
                            hardware_target=target,
                            variant=variant,
                            source_url=url,
                        )

        if not seen_any:
            self.stdout.write(self.style.SUCCESS(
                "Nothing new (or watchers still stubs). Use --apply once "
                "scrapers are implemented to materialise OSRelease rows."
            ))
