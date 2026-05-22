"""Provision an image via the user's existing `packer-arm-tools` Docker action.

The action lives at
``/home/newt/work/models/service-catalog/cicd-tools/packer-arm-tools/`` and
publishes the ``cznewt/packer-arm-tools`` Docker image with a set of preset
``configs/<name>.json`` files. The image internally invokes
``mkaczanowski/packer-builder-arm`` (loop-mount + qemu-aarch64-static +
chroot) and our shell provisioner scripts (`config_raspios.sh`,
`config_batocera.sh`, `install_salt.sh`).

This module:

* picks a preset by ``(hardware_target, operating_system, variant, with_salt)``;
* builds the env / docker-run command;
* shells out and waits for it to finish.

Disabled by default (``PACKER_ARM_TOOLS_ENABLED`` setting). The orchestrator
falls back to a logged no-op when no preset matches or when the integration
is off — see ``builds.orchestrator._mount_and_provision``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings

if TYPE_CHECKING:
    from builds.orchestrator import BuildContext


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Preset mapping — what `docker run cznewt/packer-arm-tools:* …` understands
# ---------------------------------------------------------------------------
# Key: (hardware_target_slug, operating_system_slug, variant, with_salt_minion)
# Value: preset name (the `<name>.json` config inside /configs in the image).
#
# These match the configs shipped by packer-arm-tools today. Anything not in
# this map — rpi5, pc-amd64, generic-arm64, vm-*, haos — falls through to a
# no-op so future targets can be added by appending rows here.
PRESETS: dict[tuple[str, str, str, bool], str] = {
    # Raspberry Pi 3 / 4 — RaspiOS (both "lite" and "desktop" variants), with
    # and without the salt-minion install step.
    ("rpi3", "raspios", "lite",    False): "raspberry-pi-34-raspios-server-arm64",
    ("rpi3", "raspios", "lite",    True):  "raspberry-pi-34-raspios-server-salt-minion-arm64",
    ("rpi3", "raspios", "desktop", False): "raspberry-pi-34-raspios-desktop-arm64",
    ("rpi3", "raspios", "desktop", True):  "raspberry-pi-34-raspios-desktop-salt-minion-arm64",
    ("rpi4", "raspios", "lite",    False): "raspberry-pi-34-raspios-server-arm64",
    ("rpi4", "raspios", "lite",    True):  "raspberry-pi-34-raspios-server-salt-minion-arm64",
    ("rpi4", "raspios", "desktop", False): "raspberry-pi-34-raspios-desktop-arm64",
    ("rpi4", "raspios", "desktop", True):  "raspberry-pi-34-raspios-desktop-salt-minion-arm64",
    # Raspberry Pi 4 — Ubuntu Server.
    ("rpi4", "ubuntu", "server",   False): "raspberry-pi-34-ubuntu-server-arm64",
    ("rpi4", "ubuntu", "server",   True):  "raspberry-pi-34-ubuntu-server-salt-minion-arm64",
    # Raspberry Pi 4 — Batocera (single variant).
    ("rpi4", "batocera", "",       False): "raspberry-pi-4-batocera-desktop-arm64",
}


def select_preset(
    target_slug: str,
    os_slug: str,
    variant: str,
    with_salt: bool,
) -> str | None:
    """Return the preset name for a build, or None if packer-arm-tools doesn't cover it.

    If a `with_salt=True` lookup misses, fall back to the non-salt variant so
    that recipes that *would like* a minion installed still get a working
    image instead of erroring out — the orchestrator can log this downgrade.
    """
    key = (target_slug, os_slug, variant, with_salt)
    if key in PRESETS:
        return PRESETS[key]
    if with_salt:
        return PRESETS.get((target_slug, os_slug, variant, False))
    return None


# ---------------------------------------------------------------------------
# Env + command construction
# ---------------------------------------------------------------------------


def _wants_salt(build) -> bool:
    """Read whether this build asks for a salt-minion bake-in.

    Honors ``option_values['install_salt_minion']`` (a Recipe-level option).
    """
    opts = build.option_values or {}
    return bool(opts.get("install_salt_minion"))


def build_image_variables(build, *, with_salt: bool) -> dict[str, Any]:
    """Build the IMAGE_VARIABLES JSON dict the action expects.

    Mirrors the env contract of
    ``packer-arm-tools/docker/files/actions/packer-build-arm-image``.
    """
    upstream = build.upstream_image
    opts = build.option_values or {}

    variables: dict[str, Any] = {
        "FILE_URL": upstream.source_url,
        "FILE_CHECKSUM": upstream.checksum_sha256 or "",
        "HOSTNAME": opts.get("hostname") or (build.label or f"osbakery-{build.id}"),
    }

    # Optional Wi-Fi block (config_raspios.sh / config_batocera.sh accept these).
    if opts.get("wifi_ssid"):
        variables["WPA_ESSID"] = opts["wifi_ssid"]
        variables["WPA_PASSWORD"] = opts.get("wifi_psk", "")
        variables["WPA_COUNTRY"] = opts.get("wifi_country", "DE")

    if with_salt:
        variables["SALT_VERSION"] = getattr(settings, "SALT_MINION_VERSION", "3007")
        variables["SALT_MASTER"] = getattr(settings, "SALT_MASTER_URL", "")
        variables["SALT_MINION"] = opts.get("minion_id") or (build.label or f"osbakery-{build.id}")
        # Caller is responsible for pre-issuing the keypair; orchestrator does
        # this once a real key-issuance flow is wired up. For now we pass
        # whatever's on the recipe option (likely empty).
        variables["SALT_PUB_KEY"] = opts.get("salt_pub_key", "")
        variables["SALT_PRIV_KEY"] = opts.get("salt_priv_key", "")

    return variables


def _prepare_packer_workspace(
    *,
    presets_root: Path,
    work: Path,
    preset: str,
    image_variables: dict[str, Any],
) -> Path:
    """Lay out a per-build packer workspace from the bundled presets.

    Copies the preset config + the shared `scripts/` helpers into the work
    dir and writes the variables JSON. Strips `file_checksum` from the
    preset when the build's upstream sha256 is unknown — otherwise Packer
    refuses to download the archive.
    """
    work.mkdir(parents=True, exist_ok=True)
    src = presets_root / f"{preset}.json"
    if not src.exists():
        raise FileNotFoundError(f"packer-arm-tools preset missing: {src}")

    config_path = work / "config.json"
    # Load + maybe-mutate so we can drop checksum verification when we
    # don't have one yet.
    cfg = json.loads(src.read_text())
    if not image_variables.get("FILE_CHECKSUM"):
        for builder in cfg.get("builders", []):
            builder.pop("file_checksum", None)
            builder["file_checksum_type"] = "none"
    config_path.write_text(json.dumps(cfg, indent=2))

    # The shell provisioners under scripts/ reference each other with
    # relative paths, so they live next to config.json.
    scripts_src = presets_root / "scripts"
    if scripts_src.is_dir():
        scripts_dst = work / "scripts"
        if scripts_dst.exists():
            shutil.rmtree(scripts_dst)
        shutil.copytree(scripts_src, scripts_dst)

    (work / "variables.json").write_text(
        json.dumps(image_variables, sort_keys=True, indent=2)
    )
    return config_path


def build_packer_command(*, config_path: Path) -> list[str]:
    """The actual ``packer build`` argv. Run with cwd=work_dir."""
    return [
        "packer", "build",
        "-color=false",
        "-var-file=variables.json",
        config_path.name,
    ]


# ---------------------------------------------------------------------------
# Provisioner entry point
# ---------------------------------------------------------------------------


def provision(ctx: "BuildContext") -> bool:
    """Bake the image via packer-arm-tools, in-process. Return True if it ran.

    Errors propagate as CalledProcessError; the orchestrator marks the
    build failed and surfaces stderr through the BuildEvent log.
    """
    from builds.models import BuildEvent  # local import to keep cycles tame

    build = ctx.build
    target = build.hardware_target.slug
    os_slug = build.recipe_version.recipe.operating_system.slug
    variant = build.upstream_image.variant or ""
    with_salt = _wants_salt(build)

    preset = select_preset(target, os_slug, variant, with_salt)
    if preset is None:
        BuildEvent.objects.create(
            build=build, phase="salt", level="warning",
            message=(
                f"packer-arm-tools has no preset for "
                f"({target}, {os_slug}, variant={variant!r}, with_salt={with_salt}); "
                "skipping ARM provisioner."
            ),
            data={"backend": "packer_arm_tools", "skipped": True},
        )
        return False

    if not getattr(settings, "PACKER_ARM_TOOLS_ENABLED", False):
        BuildEvent.objects.create(
            build=build, phase="salt", level="info",
            message=(
                f"packer-arm-tools matched preset {preset!r} but "
                "PACKER_ARM_TOOLS_ENABLED is False — skipping."
            ),
            data={"backend": "packer_arm_tools", "preset": preset, "dry_run": True},
        )
        return False

    if shutil.which("packer") is None:
        BuildEvent.objects.create(
            build=build, phase="salt", level="error",
            message=(
                "packer-arm-tools needs `packer` on PATH; none found. Are "
                "you running on worker-packer-arm?"
            ),
            data={"backend": "packer_arm_tools"},
        )
        return False

    presets_root = Path(getattr(
        settings, "PACKER_ARM_TOOLS_PRESETS",
        "/opt/packer-arm-tools/configs",
    ))
    image_variables = build_image_variables(build, with_salt=with_salt)
    work = ctx.work_dir / "packer-arm"
    config_path = _prepare_packer_workspace(
        presets_root=presets_root,
        work=work,
        preset=preset,
        image_variables=image_variables,
    )

    BuildEvent.objects.create(
        build=build, phase="salt", level="info",
        message=f"Running packer-arm-tools preset {preset!r}.",
        data={
            "backend": "packer_arm_tools",
            "preset": preset,
            "variable_keys": sorted(image_variables.keys()),
            "work": str(work),
        },
    )

    cmd = build_packer_command(config_path=config_path)
    env = os.environ.copy()
    env.setdefault("PACKER_PLUGIN_PATH", "/usr/bin")
    env.setdefault("PACKER_CACHE_DIR", str(work / ".packer_cache"))
    env.setdefault("PACKER_LOG", "0")
    log.info("[packer-arm] $ %s   (cwd=%s)", " ".join(cmd), work)
    try:
        completed = subprocess.run(
            cmd, cwd=work, env=env, check=True,
            capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        BuildEvent.objects.create(
            build=build, phase="salt", level="error",
            message=f"packer build failed ({exc.returncode}); see data.",
            data={
                "backend": "packer_arm_tools", "preset": preset,
                "stdout_tail": (exc.stdout or "")[-4000:],
                "stderr_tail": (exc.stderr or "")[-4000:],
            },
        )
        raise

    output = work / "output.img"
    if not output.exists():
        BuildEvent.objects.create(
            build=build, phase="salt", level="error",
            message="packer build succeeded but output.img was not produced.",
            data={
                "backend": "packer_arm_tools", "preset": preset,
                "stdout_tail": completed.stdout[-4000:],
            },
        )
        return False

    # Replace the placeholder/cached target_image with packer's output so
    # the rest of the orchestrator (pack → publish) operates on the real
    # baked rootfs.
    if ctx.target_image.exists():
        ctx.target_image.unlink()
    shutil.move(str(output), str(ctx.target_image))

    BuildEvent.objects.create(
        build=build, phase="salt", level="info",
        message=(
            f"packer-arm-tools produced {ctx.target_image.stat().st_size:,} "
            f"byte image via preset {preset!r}."
        ),
        data={"backend": "packer_arm_tools", "preset": preset},
    )
    return True
