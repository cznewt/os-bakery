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

import yaml
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

# Where salt lives on the (persistent) batocera userdata partition at runtime.
_SALT_DEVICE_ROOT = "/userdata/system/opt/salt"

_CUSTOM_MARKER = "# --- os-bakery provisioned (do not edit below) ---"


def _emit(build, phase, message, level="info", **data):
    BuildEvent.objects.create(build=build, phase=phase, message=message, level=level, data=data)


def _overlay(src: Path, dst: Path) -> tuple[int, int]:
    """Merge-copy src/* into dst/ (like cp -a), preserving modes.

    Returns (files_copied, bytes_copied) for the event log.
    """
    n_files, n_bytes = 0, 0
    for root, _dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for f in files:
            srcf = Path(root) / f
            shutil.copy2(srcf, dst / rel / f)
            n_files += 1
            try:
                n_bytes += srcf.stat().st_size
            except OSError:
                pass
    return n_files, n_bytes


def _free_mib(path: Path) -> tuple[int, int]:
    """(free_MiB, total_MiB) on the filesystem holding ``path``."""
    try:
        st = os.statvfs(path)
        return (st.f_bavail * st.f_frsize) // (1024 * 1024), \
               (st.f_blocks * st.f_frsize) // (1024 * 1024)
    except OSError:
        return 0, 0


def _emit_cmd(build, phase, label, cp) -> None:
    """Emit a command result with its captured stdout/stderr tail."""
    out = ((getattr(cp, "stdout", "") or "") + (getattr(cp, "stderr", "") or "")).strip()
    rc = getattr(cp, "returncode", 0)
    _emit(build, phase, f"{label} (rc={rc})",
          level="warning" if rc else "info",
          returncode=rc, output_tail=out[-2000:])


def _write_minion_conf(ctx: "BuildContext", system: Path) -> None:
    """Minion config pointing at the baked-in local file_roots + pillar_roots.

    With these roots present, ``salt-call --local state.apply`` (or
    ``state.highstate``) runs the recipe's states on the device with no master.
    """
    opts = ctx.build.option_values or {}
    master = getattr(settings, "SALT_MASTER_URL", "") or opts.get("salt_master", "")
    minion_id = opts.get("minion_id") or opts.get("hostname") or ctx.build.label or f"osbakery-{ctx.build.id}"
    conf: dict = {
        "id": minion_id,
        "file_roots": {"base": [f"{_SALT_DEVICE_ROOT}/states"]},
        "pillar_roots": {"base": [f"{_SALT_DEVICE_ROOT}/pillar"]},
    }
    if master:
        # Master recorded for a connected minion; --local still reads the
        # baked local roots above on demand.
        conf["master"] = master
    else:
        conf["file_client"] = "local"
    conf_dir = system / "opt/salt/conf"
    conf_dir.mkdir(parents=True, exist_ok=True)
    (conf_dir / "minion").write_text(
        yaml.safe_dump(conf, default_flow_style=False, sort_keys=False)
    )


def _stage_salt_roots(ctx: "BuildContext", system: Path) -> tuple[int, int]:
    """Bake the salt states (file_roots) + rendered pillar (pillar_roots) onto
    the userdata partition so masterless ``salt-call --local`` has them.

    Returns (state_files, pillar_files) counts for the event log.
    """
    states_src = Path(settings.SALT_STATES_ROOT)
    states_dst = system / "opt/salt/states"
    pillar_dst = system / "opt/salt/pillar"

    if states_dst.exists():
        shutil.rmtree(states_dst)
    if states_src.is_dir():
        shutil.copytree(states_src, states_dst)
    else:
        states_dst.mkdir(parents=True, exist_ok=True)
    # The state top the orchestrator decided for this build (role's states).
    if ctx.top_path.exists():
        shutil.copy2(ctx.top_path, states_dst / "top.sls")

    if pillar_dst.exists():
        shutil.rmtree(pillar_dst)
    pillar_dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(ctx.pillar_path.glob("*")):
        if f.is_file():
            shutil.copy2(f, pillar_dst / f.name)

    n_states = sum(1 for _ in states_dst.rglob("*") if _.is_file())
    n_pillar = sum(1 for _ in pillar_dst.rglob("*") if _.is_file())
    return n_states, n_pillar


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
    payload = _dir_size(*pkg_roots)
    grow_by = payload + 256 * 1024 * 1024  # payload + headroom
    img_before = ctx.target_image.stat().st_size
    _emit(build, "grow",
          f"Package payload {payload // (1024*1024)} MiB; growing image "
          f"{img_before // (1024*1024)} → {(img_before+grow_by) // (1024*1024)} MiB "
          f"(+{grow_by // (1024*1024)} MiB headroom-included).",
          payload_mib=payload // (1024*1024), grow_mib=grow_by // (1024*1024))
    ls._sh(["truncate", "-s", f"+{grow_by}", str(ctx.target_image)])

    lo: str | None = None
    mounted: list[Path] = []
    try:
        lo, parts = ls._attach_loop(ctx.target_image)
        # Log the partition table the kernel sees on the loop device.
        parts_desc = []
        for p in parts:
            fs = ls._sh(["blkid", "-o", "value", "-s", "TYPE", str(p)],
                        check=False, capture=True).stdout.strip()
            sz = int(ls._sh(["blockdev", "--getsize64", str(p)],
                            check=False, capture=True).stdout.strip() or "0")
            parts_desc.append(f"{p.name}={fs or '?'}/{sz // (1024*1024)}MiB")
        share_part, _boot = ls._classify_partitions(parts)
        partnum = share_part.name.rsplit("p", 1)[-1]
        _emit(build, "grow",
              f"Loop {lo}: {len(parts)} partitions [{', '.join(parts_desc)}]; "
              f"SHARE = {share_part.name} (part {partnum}).")

        # The image was grown by `truncate`, but the GPT's backup header still
        # marks the old disk end — so `resizepart 100%` would claim nothing.
        # `sgdisk -e` relocates the backup header to the real end first.
        _emit_cmd(build, "grow", "sgdisk -e (relocate GPT backup header)",
                  ls._sh(["sgdisk", "-e", lo], check=False, capture=True))
        ls._sh_optional(["partprobe", lo])
        ls._sh_optional(["udevadm", "settle", "--timeout=5"])
        # Now extend the partition to fill the grown disk, then resize its fs.
        _emit_cmd(build, "grow", f"parted resizepart {partnum} 100%",
                  ls._sh(["parted", "-s", lo, "resizepart", partnum, "100%"],
                         check=False, capture=True))
        ls._sh_optional(["partprobe", lo])
        ls._sh_optional(["udevadm", "settle", "--timeout=5"])
        fstype = ls._sh(["blkid", "-o", "value", "-s", "TYPE", str(share_part)],
                        check=False, capture=True).stdout.strip()
        part_mib = int(ls._sh(["blockdev", "--getsize64", str(share_part)],
                              check=False, capture=True).stdout.strip() or "0") // (1024*1024)
        _emit(build, "grow",
              f"SHARE {share_part.name}: fstype={fstype or '?'}, partition now {part_mib} MiB.",
              fstype=fstype, partition_mib=part_mib)
        if fstype == "ext4":
            _emit_cmd(build, "grow", "e2fsck -fy",
                      ls._sh(["e2fsck", "-fy", str(share_part)], check=False, capture=True))
            _emit_cmd(build, "grow", "resize2fs",
                      ls._sh(["resize2fs", str(share_part)], check=False, capture=True))
        elif fstype in {"exfat", "vfat", "fat", "msdos"}:
            _emit(build, "grow",
                  f"SHARE is {fstype} (no online grow) — overlay may still ENOSPC.",
                  level="warning")
        ls._mount(str(share_part), userdata)
        mounted.append(userdata)
        free0, total = _free_mib(userdata)
        _emit(build, "mount", f"Mounted SHARE at userdata: {free0}/{total} MiB free.",
              free_mib=free0, total_mib=total)

        system = userdata / "system"
        system.mkdir(parents=True, exist_ok=True)
        applied: list[str] = []
        for pkg in _PACKAGES:
            src = pkg_dir / pkg / "userdata" / "system"
            if not src.is_dir():
                _emit(build, "overlay", f"Package {pkg} not bundled — skipped.",
                      level="warning")
                continue
            files, nbytes = _overlay(src, system)
            free, _ = _free_mib(userdata)
            _emit(build, "overlay",
                  f"Overlaid {pkg}: {files} files, {nbytes // (1024*1024)} MiB "
                  f"→ {free} MiB free.",
                  package=pkg, files=files, mib=nbytes // (1024*1024), free_mib=free)
            applied.append(pkg)
        if not applied:
            _emit(build, "overlay", f"No batocera packages found under {pkg_dir}.",
                  level="warning")
            return False

        # Bake the salt file_roots (states) + pillar_roots so masterless
        # `salt-call --local state.apply` runs the role's states on-device.
        n_states, n_pillar = _stage_salt_roots(ctx, system)
        _emit(build, "salt-roots",
              f"Staged file_roots ({n_states} state files) + pillar_roots "
              f"({n_pillar} files) under {_SALT_DEVICE_ROOT}/{{states,pillar}}.",
              state_files=n_states, pillar_files=n_pillar)
        _write_minion_conf(ctx, system)
        opts = ctx.build.option_values or {}
        master = getattr(settings, "SALT_MASTER_URL", "") or opts.get("salt_master", "")
        _emit(build, "salt-roots",
              f"Wrote minion conf: id={opts.get('minion_id') or opts.get('hostname') or build.label}, "
              f"{'master=' + master if master else 'file_client=local'}.")
        _append_custom_sh(system, _SERVICES)
        _emit(build, "provision",
              f"First-boot custom.sh hook: enable/start {', '.join(_SERVICES)}.")
        ls.write_model_file(system, "osbakery/model.yaml", ctx.effective_model)
        free_end, _ = _free_mib(userdata)
        _emit(build, "provision",
              f"Batocera provisioned: {', '.join(applied)} + salt roots + model.yaml. "
              f"{free_end} MiB free on SHARE.",
              backend="batocera_pkg", state_files=n_states, pillar_files=n_pillar,
              free_mib=free_end)
        return True
    finally:
        for path in reversed(mounted):
            ls._sh(["umount", "-lf", str(path)], check=False)
        if lo:
            ls._sh(["losetup", "-d", lo], check=False)
