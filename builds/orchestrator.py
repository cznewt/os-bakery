"""Image orchestration: turn a queued BuildRequest into an Artifact.

The orchestrator is split into discrete phases so that each one can be
unit-tested in isolation and so the timeline of events emitted into the DB
mirrors what's happening on the host.

This is a scaffold — the system-level pieces (loop devices, guestmount,
salt-call) require root + tools that aren't appropriate to assume in a stock
unit-test environment. The shape is laid out so that a follow-up patch can
replace the ``_run_*`` placeholders with real invocations.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml
from django.conf import settings
from django.core.files.storage import storages
from django.utils import timezone

from .models import Artifact, BuildEvent, BuildRequest, DownloadToken

log = logging.getLogger(__name__)


@dataclass(slots=True)
class BuildContext:
    build: BuildRequest
    work_dir: Path
    base_image: Path
    target_image: Path
    pillar_path: Path
    top_path: Path


def _emit(build: BuildRequest, phase: str, message: str, level: str = "info", **data) -> None:
    BuildEvent.objects.create(build=build, phase=phase, message=message, level=level, data=data)


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    log.debug("$ %s", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=cwd)


def _prepare_workspace(build: BuildRequest) -> BuildContext:
    work_root: Path = settings.BUILD_WORK_ROOT
    work_dir = work_root / str(build.id)
    work_dir.mkdir(parents=True, exist_ok=True)

    upstream = build.upstream_image
    cached_local = Path(upstream.local_path) if upstream.local_path else None
    base_image = None

    # Preferred path: the upstream blob is in the artifacts S3 bucket under
    # cache/… (populated by `manage.py refresh_upstream`). Download once
    # per build into the work dir so the bake pipeline has a real rootfs
    # to operate on.
    if upstream.cache_storage_key:
        storage = storages["artifacts"]
        if storage.exists(upstream.cache_storage_key):
            base_image = work_dir / "base.img"
            _emit(
                build, "prepare",
                f"Fetching base image from S3: {upstream.cache_storage_key} "
                f"({upstream.size_bytes:,} bytes).",
            )
            with storage.open(upstream.cache_storage_key, "rb") as src, \
                    base_image.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)

    if base_image is None and cached_local and cached_local.exists():
        # Legacy: an operator pre-staged the image on a shared filesystem.
        base_image = cached_local
    elif base_image is not None:
        pass  # we already pulled from S3
    elif settings.DEBUG:
        # Dev mode — Packer hasn't refreshed this image's local mirror
        # yet. Generate a small placeholder so the rest of the pipeline
        # (provision → pack → publish to S3 + token) can run end-to-end
        # without requiring a multi-GB upstream fetch. The placeholder is
        # clearly labelled so a downstream consumer doesn't mistake it
        # for a real image.
        placeholder_mb = int(getattr(settings, "BAKERY_PLACEHOLDER_IMAGE_MB", 2))
        base_image = work_dir / "placeholder-base.img"
        marker = (
            f"OS-BAKERY PLACEHOLDER IMAGE\n"
            f"-----------------------------------------\n"
            f"build_id     {build.id}\n"
            f"recipe       {build.recipe_version.recipe.slug}\n"
            f"upstream     {upstream}\n"
            f"hardware     {build.hardware_target.slug}\n"
            f"NOT a real OS image. Packer hasn't refreshed local_path yet.\n"
        ).encode("utf-8")
        with base_image.open("wb") as fh:
            fh.write(marker)
            fh.write(b"\0" * (placeholder_mb * 1024 * 1024 - len(marker)))
        _emit(
            build, "prepare",
            f"Generated {placeholder_mb} MiB placeholder image — Packer "
            f"hasn't materialised {upstream}.local_path yet (DEBUG=True).",
            level="warning",
        )
    else:
        raise RuntimeError(
            f"Upstream image {upstream} has no local_path — "
            f"refresh it with Packer first."
        )

    target_image = work_dir / f"{build.id}.img"
    shutil.copy2(base_image, target_image)

    pillar_path = work_dir / "pillar"
    pillar_path.mkdir(exist_ok=True)
    top_path = work_dir / "top.sls"
    return BuildContext(
        build=build,
        work_dir=work_dir,
        base_image=base_image,
        target_image=target_image,
        pillar_path=pillar_path,
        top_path=top_path,
    )


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` into `base`. Lists are replaced, not concatenated."""
    result = dict(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _write_pillar(ctx: BuildContext) -> None:
    """Materialize the build's pillar tree on disk.

    Layers (later wins):

    1. Recipe version's ``pillar_overrides``.
    2. Cluster's ``parameters`` JSON (when ``build.cluster`` is set) —
       shared config like kubeadm tokens, MQTT brokers, ZeroTier network
       IDs that every device joining the cluster inherits.
    3. The user's ``option_values`` under the ``options`` key — per-build
       answers from the bake form (hostname, Wi-Fi, …).
    4. Computed osbakery metadata.
    """
    build = ctx.build
    rv = build.recipe_version

    pillar: dict = {}
    pillar = _deep_merge(pillar, rv.pillar_overrides or {})
    if build.cluster_id is not None:
        cluster_params = build.cluster.parameters or {}
        pillar = _deep_merge(pillar, cluster_params)
    pillar = _deep_merge(pillar, {"options": dict(build.option_values or {})})
    pillar = _deep_merge(pillar, {
        "osbakery": {
            "build_id": str(build.id),
            "recipe": rv.recipe.slug,
            "recipe_version": rv.version,
            "operating_system": rv.recipe.operating_system.slug,
            "hardware_target": build.hardware_target.slug,
            "label": build.label,
            "tenant": build.tenant.slug if build.tenant_id else None,
            "cluster": (f"{build.cluster.tenant.slug}/{build.cluster.slug}"
                        if build.cluster_id else None),
        },
    })

    (ctx.pillar_path / "top.sls").write_text(
        yaml.safe_dump({"base": {"*": [build.recipe_version.recipe.slug]}})
    )
    (ctx.pillar_path / f"{rv.recipe.slug}.sls").write_text(yaml.safe_dump(pillar))


def _write_top(ctx: BuildContext) -> None:
    """Decide which Salt states will be run inside the chrooted image."""
    rv = ctx.build.recipe_version
    inline = (rv.salt_top_yaml or "").strip()
    if inline:
        ctx.top_path.write_text(inline)
        return
    states = list(rv.salt_states or [])
    if not states:
        states = [rv.recipe.slug]
    ctx.top_path.write_text(yaml.safe_dump({"base": {"*": states}}))


def _has_salt_to_apply(ctx: BuildContext) -> bool:
    """Does this build actually have Salt states to bake in?

    True when the recipe ships an explicit top, named states, or the build
    asked for a salt bake-in via ``install_salt_minion``. Avoids running a
    masterless highstate that would only error on a missing ``<slug>.sls``.
    """
    rv = ctx.build.recipe_version
    if (rv.salt_top_yaml or "").strip():
        return True
    if list(rv.salt_states or []):
        return True
    return bool((ctx.build.option_values or {}).get("install_salt_minion"))


def _mount_and_provision(ctx: BuildContext) -> None:
    """Provision the image: masterless ``salt-call --local`` is the primary path.

    The ``local_salt`` backend loop-mounts the image and runs ``salt-call
    --local`` in a (qemu-emulated, for foreign arch) chroot — no Salt master.
    ``packer_arm_tools`` is kept as a legacy fallback for environments where
    the in-house chroot path isn't available. If neither runs, the image ships
    as the unmodified upstream base.
    """
    from builds.provisioners import local_salt, packer_arm_tools

    if _has_salt_to_apply(ctx):
        if local_salt.provision(ctx):
            return
    else:
        _emit(
            ctx.build, "salt",
            "Recipe defines no Salt states — skipping masterless bake.",
            level="info",
        )

    # Legacy backend (master-connected minion via packer-arm-tools chroot).
    if packer_arm_tools.provision(ctx):
        return

    _emit(
        ctx.build,
        "salt",
        "No provisioner backend handled this build — image will ship as the upstream base.",
        level="warning",
        target=str(ctx.target_image),
        states=str(ctx.top_path),
    )


def _pack(ctx: BuildContext) -> Path:
    """Compress the customized image to ``img.xz`` for distribution."""
    compressed = ctx.target_image.with_suffix(ctx.target_image.suffix + ".xz")
    # xz -T0 keeps it fast on big rigs; -9e for tighter compression in CI.
    _run(["xz", "-T0", "-z", "-f", str(ctx.target_image)])
    return compressed


def _sha256(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _publish(ctx: BuildContext, packed: Path) -> Artifact:
    storage = storages["artifacts"]
    digest, size = _sha256(packed)
    target_key = f"{ctx.build.id}/{packed.name}"

    # Re-bake case: drop the previous Artifact + cascading DownloadTokens
    # (Artifact is OneToOne to BuildRequest) before publishing the new one.
    # The old object lingers in S3 storage under its prior key — orphaned
    # files are reaped by a future cleanup pass.
    Artifact.objects.filter(build=ctx.build).delete()

    with packed.open("rb") as fh:
        storage.save(target_key, fh)

    media_type = "application/x-xz" if packed.suffix == ".xz" else "application/octet-stream"
    expires = timezone.now() + timezone.timedelta(days=30)
    artifact = Artifact.objects.create(
        build=ctx.build,
        storage_key=target_key,
        filename=packed.name,
        format=Artifact.Format.IMG_XZ,
        size_bytes=size,
        sha256=digest,
        media_type=media_type,
        expires_at=expires,
    )
    DownloadToken.objects.create(
        artifact=artifact,
        expires_at=timezone.now()
        + timezone.timedelta(hours=settings.DOWNLOAD_TOKEN_TTL_HOURS),
        issued_to=ctx.build.requester,
        note="Auto-issued on successful build.",
    )
    return artifact


def bake(build: BuildRequest) -> Artifact:
    """End-to-end driver invoked by the Celery task."""
    _emit(build, "prepare", "Provisioning workspace")
    ctx = _prepare_workspace(build)

    _emit(build, "pillar", "Materialising pillar + top.sls")
    _write_pillar(ctx)
    _write_top(ctx)

    build.status = BuildRequest.Status.BUILDING
    build.save(update_fields=["status"])
    _emit(build, "mount", "Mounting base image and running salt-call")
    _mount_and_provision(ctx)

    build.status = BuildRequest.Status.FINALIZING
    build.save(update_fields=["status"])
    _emit(build, "pack", "Packing artifact")
    packed = _pack(ctx)

    artifact = _publish(ctx, packed)
    _emit(build, "publish", f"Artifact published: {artifact.filename}")
    return artifact
