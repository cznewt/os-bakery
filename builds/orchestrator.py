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
    if not upstream.local_path:
        raise RuntimeError(
            f"Upstream image {upstream} has no local_path — refresh it with Packer first."
        )

    base_image = Path(upstream.local_path)
    if not base_image.exists():
        raise FileNotFoundError(f"Base image missing on disk: {base_image}")

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


def _write_pillar(ctx: BuildContext) -> None:
    """Materialize the build's pillar tree on disk.

    The pillar contains:

    * the recipe version's ``pillar_overrides``
    * the user's ``option_values`` under the ``options`` key
    * computed metadata (hardware target slug, OS slug, build id)
    """
    build = ctx.build
    rv = build.recipe_version
    pillar = {
        "osbakery": {
            "build_id": str(build.id),
            "recipe": rv.recipe.slug,
            "recipe_version": rv.version,
            "operating_system": rv.recipe.operating_system.slug,
            "hardware_target": build.hardware_target.slug,
            "label": build.label,
        },
        "options": dict(build.option_values or {}),
    }
    overrides = rv.pillar_overrides or {}
    pillar.update(overrides)

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


def _mount_and_provision(ctx: BuildContext) -> None:
    """Mount the image read-write and run salt-call against it.

    Production implementation should:

      * losetup -fP /path/to/image  (or guestmount via libguestfs)
      * mount partitions under {workdir}/rootfs
      * bind-mount /proc /sys /dev
      * copy ctx.top_path to /srv/salt/top.sls inside the rootfs
      * copy ctx.pillar_path to /srv/pillar/ inside the rootfs
      * arch-chroot rootfs salt-call --local state.apply
      * unmount and detach loop devices

    The scaffold short-circuits and records the intent so unit tests can run
    without root or libguestfs installed.
    """
    _emit(
        ctx.build,
        "salt",
        "Skipping mount+salt-call (orchestrator scaffold).",
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
