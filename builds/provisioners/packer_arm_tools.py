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
import shutil
import subprocess
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


def build_docker_command(
    *,
    image: str,
    preset: str,
    image_name: str,
    build_path: str,
    image_variables: dict[str, Any],
) -> list[str]:
    """Build the ``docker run …`` argv for one bake.

    Mirrors the invocation pattern from
    ``packer-arm-tools/justfile`` (the ``test-…-image`` recipes).
    """
    return [
        "docker", "run", "-i", "--rm=true", "--privileged",
        "-v", "/dev:/dev",
        "-v", f"{build_path}:/build",
        "-e", "BUILD_PATH=/build",
        "-e", f"IMAGE_VARIABLES={json.dumps(image_variables, sort_keys=True)}",
        "-e", f"IMAGE_NAME={image_name}",
        "-e", f"IMAGE_TEMPLATE={preset}",
        image,
        "packer-build-arm-image",
    ]


# ---------------------------------------------------------------------------
# Provisioner entry point
# ---------------------------------------------------------------------------


def provision(ctx: "BuildContext") -> bool:
    """Bake the image via packer-arm-tools. Return True if it ran.

    The function emits BuildEvents for visibility but does NOT swallow errors
    — a non-zero exit from the Docker run propagates as ``CalledProcessError``
    so the orchestrator marks the build failed.
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

    enabled = getattr(settings, "PACKER_ARM_TOOLS_ENABLED", False)
    if not enabled:
        BuildEvent.objects.create(
            build=build, phase="salt", level="info",
            message=(
                f"packer-arm-tools matched preset {preset!r} but "
                "PACKER_ARM_TOOLS_ENABLED is False — skipping (set the flag "
                "and ensure Docker + the cznewt/packer-arm-tools image are "
                "available to enable)."
            ),
            data={"backend": "packer_arm_tools", "preset": preset, "dry_run": True},
        )
        return False

    if shutil.which("docker") is None:
        BuildEvent.objects.create(
            build=build, phase="salt", level="error",
            message="packer-arm-tools needs Docker on PATH; none found.",
            data={"backend": "packer_arm_tools"},
        )
        return False

    image = getattr(
        settings, "PACKER_ARM_TOOLS_IMAGE",
        "docker.io/cznewt/packer-arm-tools:latest",
    )
    image_variables = build_image_variables(build, with_salt=with_salt)
    image_name = f"osbakery-{build.id}"
    cmd = build_docker_command(
        image=image,
        preset=preset,
        image_name=image_name,
        build_path=str(ctx.work_dir),
        image_variables=image_variables,
    )

    BuildEvent.objects.create(
        build=build, phase="salt", level="info",
        message=f"Dispatching packer-arm-tools preset {preset!r}.",
        data={
            "backend": "packer_arm_tools",
            "preset": preset,
            "image": image,
            # don't log secrets verbatim
            "variable_keys": sorted(image_variables.keys()),
        },
    )
    log.info("$ %s", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ctx.work_dir)

    # The action writes `${IMAGE_NAME}.img` into BUILD_PATH; the orchestrator
    # will pick that up as the new target image to pack.
    new_image = ctx.work_dir / f"{image_name}.img"
    if new_image.exists():
        ctx.target_image = new_image

    BuildEvent.objects.create(
        build=build, phase="salt", level="info",
        message=f"packer-arm-tools finished — target image is {new_image.name}.",
        data={"backend": "packer_arm_tools", "preset": preset},
    )
    return True
