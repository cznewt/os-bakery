"""Signal handlers wired up by ``BuildsConfig.ready``."""

from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import BuildRequest

log = logging.getLogger(__name__)


@receiver(post_save, sender=BuildRequest)
def enqueue_new_build_requests(sender, instance: BuildRequest, created: bool, **kwargs) -> None:
    """When a build is freshly created in QUEUED state, dispatch the Celery task.

    Swallows broker-unreachable errors so the request itself still lands —
    devs running without redis can poke the UI; an operator can re-dispatch
    later via the admin.
    """
    if not created or instance.status != BuildRequest.Status.QUEUED:
        return

    # Local import to avoid loading Celery at app-ready time during migrations.
    from .tasks import run_build

    try:
        async_result = run_build.apply_async(args=[str(instance.id)], queue="builds")
    except Exception as exc:
        log.warning(
            "Could not enqueue build %s — broker unreachable? (%s)", instance.id, exc
        )
        return
    BuildRequest.objects.filter(pk=instance.pk).update(celery_task_id=async_result.id)
    log.info("Dispatched build %s as celery task %s", instance.id, async_result.id)
