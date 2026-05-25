"""Render a BuildRequest into an Argo Workflow manifest.

Each WorkflowStep of the build's provisioner becomes a container template; the
steps run in sequence and hand the working image to the next via the S3
artifact store, keyed on BUILD_ID (same store the in-process worker pushes to).
Containers are parameterised purely by env vars.

This is a pure function — it produces a dict you serialise to YAML — so it's
testable without a cluster. Submitting it (kube creds + Argo Workflows
installed + an S3 artifact repo) is a separate, infra-dependent concern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from builds.models import BuildRequest


def build_env(build: "BuildRequest") -> dict[str, str]:
    """The build-wide env every step receives (steps add/override their own)."""
    rv = build.recipe_version
    recipe = rv.recipe
    upstream = build.upstream_image
    opts = build.option_values or {}
    prov = recipe.provisioner.slug if recipe.provisioner_id else "salt"
    return {
        "BUILD_ID": str(build.id),
        "OS_SLUG": recipe.operating_system.slug,
        "RECIPE": recipe.slug,
        "RECIPE_VERSION": rv.version,
        "PROVISIONER": prov,
        "HARDWARE_TARGET": build.hardware_target.slug,
        "ARCH": getattr(build.hardware_target.architecture, "slug", ""),
        "VARIANT": upstream.variant or "",
        "FILE_URL": upstream.source_url,
        "FILE_CHECKSUM": upstream.checksum_sha256 or "",
        "CACHE_KEY": upstream.cache_storage_key or "",
        "HOSTNAME": opts.get("hostname") or build.label or f"osbakery-{build.id}",
        # S3 artifact store — steps read/write work/<BUILD_ID>/… and the final
        # step publishes the artifact, exactly like the worker does today.
        "ARTIFACT_BUCKET": getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or "",
        "S3_ENDPOINT": getattr(settings, "AWS_S3_ENDPOINT_URL", "") or "",
        "WORK_PREFIX": f"work/{build.id}",
    }


def build_argo_workflow(build: "BuildRequest") -> dict:
    """Build an Argo `Workflow` manifest (dict) for a BuildRequest.

    Resolves the ordered steps from the recipe's provisioner. Each step is a
    container template; a `main` steps-template runs them in sequence.
    """
    rv = build.recipe_version
    prov = rv.recipe.provisioner
    steps = list(prov.steps.all()) if prov else []
    base = build_env(build)

    templates: list[dict] = [{"name": "main", "steps": []}]
    for st in steps:
        env = dict(base)
        env.update({k: str(v) for k, v in (st.env or {}).items()})
        container: dict = {
            "image": st.image,
            "env": [{"name": k, "value": v} for k, v in env.items()],
        }
        if st.command:
            container["command"] = st.command
        templates.append({"name": st.name, "container": container})
        # Sequential: one step per stage (each its own [{…}] list).
        templates[0]["steps"].append([{"name": st.name, "template": st.name}])

    return {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Workflow",
        "metadata": {
            "generateName": f"bake-{rv.recipe.slug}-",
            "labels": {
                "osbakery/build-id": str(build.id),
                "osbakery/recipe": rv.recipe.slug,
                "osbakery/provisioner": prov.slug if prov else "salt",
            },
        },
        "spec": {
            "entrypoint": "main",
            "templates": templates,
        },
    }
