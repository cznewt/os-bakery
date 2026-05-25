"""Render a build's Argo Workflow manifest to stdout (for inspection)."""

from __future__ import annotations

import yaml
from django.core.management.base import BaseCommand, CommandError

from builds.models import BuildRequest
from builds.workflow import build_argo_workflow


class Command(BaseCommand):
    help = "Print the Argo Workflow YAML for a BuildRequest."

    def add_arguments(self, parser) -> None:
        parser.add_argument("build_id", help="BuildRequest UUID.")

    def handle(self, *args, build_id: str, **options) -> None:
        try:
            build = BuildRequest.objects.select_related(
                "recipe_version__recipe__provisioner",
                "recipe_version__recipe__operating_system",
                "hardware_target__architecture",
                "upstream_image",
            ).get(pk=build_id)
        except BuildRequest.DoesNotExist as exc:
            raise CommandError(f"No build {build_id}") from exc
        self.stdout.write(yaml.safe_dump(build_argo_workflow(build), sort_keys=False))
