"""Queue BuildRequest rows for the gedu Batocera fleet.

Mirrors the nodes defined in gedu's salt model
(`/home/newt/work/models/gedu-sites-model/inventory/targets/gedu-prg-infra/gedu-prg-infra-salt.yml`):

  Arcade machines (PRG datacenter):
    gedu-prg-arcade-alpha    pc-amd64    batocera-arcade   gedu-arcade
    gedu-prg-arcade-bravo    pc-amd64    batocera-arcade   gedu-arcade
    gedu-prg-arcade-charlie  pc-amd64    batocera-arcade   gedu-arcade
    gedu-prg-arcade-delta    pc-amd64    batocera-arcade   gedu-arcade

  Roaming handhelds (ZeroTier nxlabs-geekedu mesh):
    gedu-roam-pam-daw        rg353p      batocera-handheld gedu-roam
    gedu-roam-pam-kubik      rg353p      batocera-handheld gedu-roam
    gedu-roam-pam-newt       rg353p      batocera-handheld gedu-roam
    gedu-roam-pam-echo       rg353p      batocera-handheld gedu-roam

Re-running the command updates the option_values + cluster on the
existing row (matched by `label`) instead of duplicating the queue.
The BuildRequest post_save signal dispatches each to the Celery
worker on creation; existing rows are *not* re-enqueued unless you
pass ``--requeue`` (which resets status to QUEUED before saving).
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from builds.models import BuildRequest
from catalog.models import HardwareTarget, UpstreamImage
from recipes.models import Recipe
from tenants.models import Cluster, Tenant


ARCADE_NODES: list[tuple[str, str]] = [
    # (hostname-suffix, EmulationStation netplay nickname)
    ("alpha",   "Alpha"),
    ("bravo",   "Bravo"),
    ("charlie", "Charlie"),
    ("delta",   "Delta"),
]

ROAM_HANDHELDS: list[tuple[str, str]] = [
    ("pam-daw",   "Daw"),
    ("pam-kubik", "Kubari"),
    ("pam-newt",  "Newt"),
    ("pam-echo",  "Echo"),
]


class Command(BaseCommand):
    help = "Queue Batocera BuildRequest rows for the gedu fleet."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--requeue", action="store_true",
            help="Reset existing builds to status=QUEUED before saving so "
                 "the Celery worker re-processes them.",
        )
        parser.add_argument(
            "--arcade-target", default="pc-amd64",
            help="HardwareTarget slug for the arcade nodes (default pc-amd64).",
        )
        parser.add_argument(
            "--handheld-target", default="rg353p",
            help="HardwareTarget slug for the roaming nodes (default rg353p).",
        )

    @transaction.atomic
    def handle(self, *args, requeue: bool = False,
               arcade_target: str = "pc-amd64",
               handheld_target: str = "rg353p", **options) -> None:
        gedu = Tenant.objects.filter(slug="gedu").first()
        if gedu is None:
            raise CommandError(
                "Tenant 'gedu' missing — run `manage.py seed_tenants` first."
            )

        arcade_cluster = Cluster.objects.get(tenant=gedu, slug="gedu-arcade")
        roam_cluster = Cluster.objects.get(tenant=gedu, slug="gedu-roam")

        arcade_recipe = Recipe.objects.get(slug="batocera-arcade")
        arcade_version = (arcade_recipe.versions.filter(is_current=True).first()
                          or arcade_recipe.versions.order_by("-created_at").first())
        handheld_recipe = Recipe.objects.get(slug="batocera-handheld")
        handheld_version = (handheld_recipe.versions.filter(is_current=True).first()
                            or handheld_recipe.versions.order_by("-created_at").first())

        arcade_target_obj = HardwareTarget.objects.get(slug=arcade_target)
        handheld_target_obj = HardwareTarget.objects.get(slug=handheld_target)

        arcade_image = self._pick_image("batocera", arcade_target_obj)
        handheld_image = self._pick_image("batocera", handheld_target_obj)

        for suffix, nickname in ARCADE_NODES:
            hostname = f"gedu-prg-arcade-{suffix}"
            self._upsert(
                label=hostname,
                version=arcade_version,
                target=arcade_target_obj,
                image=arcade_image,
                cluster=arcade_cluster,
                tenant=gedu,
                option_values={
                    "hostname": hostname,
                    "cabinet_name": nickname,
                    "wifi_ssid": "gedu",
                    "wifi_psk": "scholaludus",
                },
                requeue=requeue,
            )

        for suffix, nickname in ROAM_HANDHELDS:
            hostname = f"gedu-roam-{suffix}"
            self._upsert(
                label=hostname,
                version=handheld_version,
                target=handheld_target_obj,
                image=handheld_image,
                cluster=roam_cluster,
                tenant=gedu,
                option_values={
                    "hostname": hostname,
                    "language": "cs_CZ",
                    "wifi_ssid": "gedu",
                    "wifi_psk": "scholaludus",
                },
                requeue=requeue,
            )

        self.stdout.write(self.style.SUCCESS(
            f"Queued {len(ARCADE_NODES)} arcade + {len(ROAM_HANDHELDS)} "
            "roaming builds. Track them in /admin/builds/buildrequest/ "
            "or via `docker compose logs -f worker`."
        ))

    # -----------------------------------------------------------------

    def _pick_image(self, os_slug: str, target: HardwareTarget) -> UpstreamImage:
        img = (UpstreamImage.objects
               .filter(release__operating_system__slug=os_slug,
                       hardware_target=target)
               .order_by("-release__version").first())
        if img is None:
            raise CommandError(
                f"No UpstreamImage for {os_slug} on {target.slug} — run "
                "`manage.py seed_catalog` first."
            )
        return img

    def _upsert(self, *, label: str, version, target, image,
                cluster, tenant, option_values: dict[str, Any],
                requeue: bool) -> None:
        existing = BuildRequest.objects.filter(label=label).first()
        if existing is None:
            build = BuildRequest.objects.create(
                recipe_version=version,
                hardware_target=target,
                upstream_image=image,
                cluster=cluster,
                tenant=tenant,
                option_values=option_values,
                label=label,
                status=BuildRequest.Status.QUEUED,
            )
            self.stdout.write(f"  [created]  {build.id}  {label}")
            return

        existing.recipe_version = version
        existing.hardware_target = target
        existing.upstream_image = image
        existing.cluster = cluster
        existing.tenant = tenant
        existing.option_values = option_values
        if requeue:
            existing.status = BuildRequest.Status.QUEUED
            existing.failure_reason = ""
            existing.started_at = None
            existing.finished_at = None
        existing.save()
        if requeue:
            # post_save signal only fires for created=True, so requeues need
            # explicit dispatch.
            from builds.tasks import run_build
            try:
                async_result = run_build.apply_async(
                    args=[str(existing.id)], queue="builds",
                )
                BuildRequest.objects.filter(pk=existing.pk).update(
                    celery_task_id=async_result.id,
                )
            except Exception as exc:  # broker unreachable in dev → log & move on
                self.stdout.write(self.style.WARNING(
                    f"    Could not dispatch {existing.id} to broker: {exc}"
                ))
        self.stdout.write(
            f"  [{'requeued' if requeue else 'updated '}] {existing.id}  {label}"
        )
