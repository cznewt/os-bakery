"""Batocera provisioner — overlay pacman packages into the userdata partition.

Batocera is buildroot (no apt/chroot-exec). Apps ship as pacman packages that
overlay ``/userdata/system/`` with prebuilt per-arch binaries + a batocera
service. So baking = mount the image's userdata (SHARE) partition and copy the
bundled packages' ``userdata/system/`` tree in, write the salt minion config,
and append a first-boot hook to ``custom.sh`` that installs/enables the
services (what ``batocera-services enable`` + the package's batoexec do).

Packages are bundled into the worker image at $BATOCERA_PACKAGES_DIR
(per-arch). No qemu/chroot needed — it's pure file injection.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

from builds.models import BuildEvent
from builds.provisioners import local_salt as ls

if TYPE_CHECKING:
    from builds.orchestrator import BuildContext

log = logging.getLogger(__name__)

# Packages overlaid into every batocera bake, in order.
_PACKAGES = ["misc-salt-3007.8", "misc-alloy-1.11.3"]
# Their batocera service names (for the first-boot enable hook).
_SERVICES = ["salt_minion", "alloy"]

_CUSTOM_MARKER = "# --- os-bakery provisioned (do not edit below) ---"


def _emit(build, phase, message, level="info", **data):
    BuildEvent.objects.create(build=build, phase=phase, message=message, level=level, data=data)


def _overlay(src: Path, dst: Path) -> None:
    """Merge-copy src/* into dst/ (like cp -a), preserving modes."""
    for root, _dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(Path(root) / f, dst / rel / f)


def _write_minion_conf(ctx: "BuildContext", system: Path) -> None:
    opts = ctx.build.option_values or {}
    master = getattr(settings, "SALT_MASTER_URL", "") or opts.get("salt_master", "")
    minion_id = opts.get("minion_id") or opts.get("hostname") or ctx.build.label or f"osbakery-{ctx.build.id}"
    conf_dir = system / "opt/salt/conf"
    conf_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"id: {minion_id}"]
    if master:
        lines.append(f"master: {master}")
    else:
        lines.append("file_client: local")  # masterless if no master configured
    (conf_dir / "minion").write_text("\n".join(lines) + "\n")


def _append_custom_sh(system: Path, services: list[str]) -> None:
    """Idempotent first-boot hook: init salt + enable/start the services."""
    custom = system / "custom.sh"
    existing = custom.read_text() if custom.exists() else ""
    if _CUSTOM_MARKER in existing:
        return
    block = [_CUSTOM_MARKER, "if [ ! -f /userdata/system/.osbakery-provisioned ]; then"]
    block.append("  [ -x /userdata/system/bin/salt-init-minion ] && /userdata/system/bin/salt-init-minion || true")
    for svc in services:
        block.append(f"  batocera-services enable {svc} 2>/dev/null || true")
        block.append(f"  batocera-services start {svc} 2>/dev/null || true")
    block.append("  touch /userdata/system/.osbakery-provisioned")
    block.append("fi")
    header = existing if existing.startswith("#!") else "#!/bin/bash\n" + existing
    custom.write_text(header.rstrip() + "\n\n" + "\n".join(block) + "\n")
    custom.chmod(0o755)


def _dir_size(*roots: Path) -> int:
    total = 0
    for r in roots:
        if not r.is_dir():
            continue
        for d, _sub, files in os.walk(r):
            for f in files:
                try:
                    total += (Path(d) / f).stat().st_size
                except OSError:
                    pass
    return total


def provision(ctx: "BuildContext") -> bool:
    build = ctx.build
    pkg_dir = Path(os.environ.get("BATOCERA_PACKAGES_DIR", "/opt/batocera-packages"))
    if not pkg_dir.is_dir():
        _emit(build, "provision",
              f"Batocera packages dir {pkg_dir} not bundled in this worker — "
              "shipping the base image.", level="warning")
        return False

    userdata = ctx.work_dir / "userdata"
    userdata.mkdir(exist_ok=True)
    _emit(build, "provision", "Batocera: overlaying packages into the userdata partition.",
          backend="batocera_pkg")

    # The fresh batocera image ships a tiny SHARE partition (it self-grows on
    # first boot); the salt+alloy binaries don't fit. So grow the image file
    # and the SHARE partition here, before mounting, then resize its fs.
    pkg_roots = [pkg_dir / pkg / "userdata" / "system" for pkg in _PACKAGES]
    grow_by = _dir_size(*pkg_roots) + 256 * 1024 * 1024  # payload + headroom
    ls._sh(["truncate", "-s", f"+{grow_by}", str(ctx.target_image)])

    lo: str | None = None
    mounted: list[Path] = []
    try:
        lo, parts = ls._attach_loop(ctx.target_image)
        # Batocera: the SHARE/userdata partition is the largest non-vfat one.
        share_part, _boot = ls._classify_partitions(parts)
        partnum = share_part.name.rsplit("p", 1)[-1]
        # The image was grown by `truncate`, but the GPT's backup header still
        # marks the old disk end — so `resizepart 100%` would claim nothing.
        # `sgdisk -e` relocates the backup header to the real end first.
        ls._sh(["sgdisk", "-e", lo], check=False)
        ls._sh_optional(["partprobe", lo])
        ls._sh_optional(["udevadm", "settle", "--timeout=5"])
        # Now extend the partition to fill the grown disk, then resize its fs.
        ls._sh(["parted", "-s", lo, "resizepart", partnum, "100%"], check=False)
        ls._sh_optional(["partprobe", lo])
        ls._sh_optional(["udevadm", "settle", "--timeout=5"])
        fstype = ls._sh(["blkid", "-o", "value", "-s", "TYPE", str(share_part)],
                        check=False, capture=True).stdout.strip()
        _emit(build, "provision",
              f"Batocera SHARE: fstype={fstype or '?'}, grew image +{grow_by // (1024 * 1024)}MiB.",
              fstype=fstype, grow_mib=grow_by // (1024 * 1024))
        if fstype == "ext4":
            ls._sh(["e2fsck", "-fy", str(share_part)], check=False)
            ls._sh(["resize2fs", str(share_part)], check=False)
        elif fstype in {"exfat", "vfat", "fat", "msdos"}:
            _emit(build, "provision",
                  f"SHARE is {fstype} (no online grow) — overlay may still ENOSPC.",
                  level="warning")
        ls._mount(str(share_part), userdata)
        mounted.append(userdata)

        system = userdata / "system"
        system.mkdir(parents=True, exist_ok=True)
        applied: list[str] = []
        for pkg in _PACKAGES:
            src = pkg_dir / pkg / "userdata" / "system"
            if src.is_dir():
                _overlay(src, system)
                applied.append(pkg)
        if not applied:
            _emit(build, "provision", f"No batocera packages found under {pkg_dir}.",
                  level="warning")
            return False

        _write_minion_conf(ctx, system)
        _append_custom_sh(system, _SERVICES)
        _emit(build, "provision",
              f"Batocera: overlaid {', '.join(applied)} + salt minion config + "
              "first-boot service enable.", backend="batocera_pkg")
        return True
    finally:
        for path in reversed(mounted):
            ls._sh(["umount", "-lf", str(path)], check=False)
        if lo:
            ls._sh(["losetup", "-d", lo], check=False)
