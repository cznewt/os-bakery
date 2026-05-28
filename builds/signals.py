"""Signal handlers wired up by ``BuildsConfig.ready``."""

from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import BuildRequest

log = logging.getLogger(__name__)


def route_queue_for_build(build: BuildRequest) -> str:
    """Pick the Celery queue for a build based on its OS + hardware target.

    Three workers subscribe to distinct queues (see compose.yaml):

      builds-esphome      — ESPHome firmware compile (esphome OS).
      builds-packer-arm   — ALL arm64/armhf bakes. Baking an arm rootfs
                            chroots in and runs the guest's own binaries under
                            qemu-*-static, which only this worker ships — so
                            pc-arm64 (UEFI) and arm64 cloud images need it just
                            like a Pi / uboot board.
      builds-packer       — everything else: x86 PCs, VMs, the catch-all.
    """
    os_slug = build.recipe_version.recipe.operating_system.slug
    if os_slug == "esphome":
        return "builds-esphome"
    target = build.hardware_target
    arch_slug = target.architecture.slug
    if arch_slug in {"arm64", "armhf"}:
        # Boot method is irrelevant — the chroot salt-call exec's arm binaries
        # under qemu emulation, available only on the ARM worker.
        return "builds-packer-arm"
    return "builds-packer"


@receiver(post_save, sender=BuildRequest)
def enqueue_new_build_requests(sender, instance: BuildRequest, created: bool, **kwargs) -> None:
    """When a build is freshly created in QUEUED state, dispatch the Celery task.

    Routes to the per-builder queue chosen by ``route_queue_for_build``.
    Swallows broker-unreachable errors so the request itself still lands —
    devs running without redis can poke the UI; an operator can re-dispatch
    later via the admin.
    """
    if not created or instance.status != BuildRequest.Status.QUEUED:
        return

    # Local import to avoid loading Celery at app-ready time during migrations.
    from .tasks import run_build

    queue = route_queue_for_build(instance)
    try:
        async_result = run_build.apply_async(args=[str(instance.id)], queue=queue)
    except Exception as exc:
        log.warning(
            "Could not enqueue build %s on %s — broker unreachable? (%s)",
            instance.id, queue, exc,
        )
        return
    BuildRequest.objects.filter(pk=instance.pk).update(celery_task_id=async_result.id)
    log.info("Dispatched build %s as celery task %s on queue %s",
             instance.id, async_result.id, queue)
