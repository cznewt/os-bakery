"""Celery tasks for the catalog app."""

from __future__ import annotations

import logging

from celery import shared_task
from django.core.management import call_command

from catalog.models import UpstreamImage

log = logging.getLogger(__name__)


@shared_task(name="catalog.tasks.mirror_upstream_image")
def mirror_upstream_image(image_id: int, force: bool = False) -> str:
    """Download + decompress + cache one UpstreamImage into the artifacts store.

    Thin wrapper over the ``refresh_upstream`` management command, scoped to a
    single image's (os, target, release, variant) so the UI's per-row "sync"
    button can enqueue it. Runs on the default queue (the packer worker), which
    has the bandwidth + tools for multi-GB pulls.
    """
    img = UpstreamImage.objects.select_related(
        "release__operating_system", "hardware_target",
    ).get(pk=image_id)
    log.info("Mirroring upstream image %s (force=%s)", img, force)
    try:
        call_command(
            "refresh_upstream",
            os=img.release.operating_system.slug,
            target=img.hardware_target.slug,
            release=img.release.version,
            variant=img.variant or "",
            force=force,
        )
    finally:
        # If the pull didn't produce a cached blob (error/no match), clear the
        # syncing marker so the row reverts to "remote" instead of being stuck
        # on "syncing". On success refresh_upstream has set cache_storage_key,
        # so is_cached wins and we leave the marker (harmless).
        img.refresh_from_db()
        if not img.cache_storage_key:
            UpstreamImage.objects.filter(pk=img.pk).update(mirror_started_at=None)
    return img.cache_storage_key or "skipped"
