"""Celery tasks that drive image builds.

The actual ``run_build`` flow is intentionally a thin Python wrapper around
shell tools. It coordinates:

* mirroring the upstream image (Packer-produced base image cache)
* mounting the image read-write (``losetup`` + ``mount`` on Linux,
  or ``guestmount`` for cases where loopback isn't viable)
* writing a per-build pillar tree from recipe options
* running ``salt-call --local`` against that pillar with the recipe's states
* unmounting cleanly and repackaging the customized image
* hashing + writing the resulting artifact into the configured storage backend

This module exposes the Celery task surface — the heavy lifting lives in
``builds.orchestrator`` (added in a follow-up).
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from .models import BuildEvent, BuildRequest

log = logging.getLogger(__name__)


def _record(build: BuildRequest, phase: str, message: str, level: str = "info", **data) -> None:
    BuildEvent.objects.create(
        build=build,
        phase=phase,
        message=message,
        level=level,
        data=data,
    )


@shared_task(bind=True, name="builds.tasks.run_build", acks_late=True)
def run_build(self, build_id: str) -> str:
    """Run a queued build to completion.

    This is the production task body's placeholder — it transitions the build
    through its lifecycle states and writes timeline events, but the actual
    mount/salt/pack steps are handed off to :mod:`builds.orchestrator` when
    that module is in place.
    """
    build = BuildRequest.objects.select_related(
        "recipe_version__recipe",
        "hardware_target__architecture",
        "upstream_image__release",
    ).get(pk=build_id)

    log.info("Picking up build %s", build.id)
    build.status = BuildRequest.Status.PREPARING
    build.started_at = timezone.now()
    build.save(update_fields=["status", "started_at"])
    _record(build, "prepare", "Build picked up by worker", task_id=self.request.id)

    try:
        from .orchestrator import bake  # imported lazily; module may be a stub

        bake(build)
    except ImportError:
        # Orchestrator not implemented yet — leave the build queued so a real
        # worker can claim it once the orchestrator lands.
        log.warning(
            "builds.orchestrator not available; leaving build %s in PREPARING state",
            build.id,
        )
        _record(
            build,
            "prepare",
            "Orchestrator module not yet implemented; build held for retry",
            level="warning",
        )
        return "deferred"
    except Exception as exc:  # noqa: BLE001 - surface any failure
        log.exception("Build %s failed", build.id)
        build.status = BuildRequest.Status.FAILED
        build.failure_reason = str(exc)
        build.finished_at = timezone.now()
        build.save(update_fields=["status", "failure_reason", "finished_at"])
        _record(build, "error", str(exc), level="error")
        raise

    build.status = BuildRequest.Status.SUCCEEDED
    build.finished_at = timezone.now()
    build.save(update_fields=["status", "finished_at"])
    _record(build, "done", "Build succeeded")
    return "ok"
