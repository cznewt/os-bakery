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
        # Load custom .py modules straight from these dirs at minion startup —
        # the batocera salt package convention (see misc-salt salt-init-minion),
        # which we must replicate here because writing this conf pre-empts that
        # script's own block. Custom grains (machine_model, usb_devices,
        # batocera_resolution) and the batocera state/exec modules live here and
        # must be present BEFORE the first state run, so file_roots `_grains`/
        # `_modules` + saltutil.sync isn't enough on its own.
        "module_dirs": [f"{_SALT_DEVICE_ROOT}/modules"],
        "states_dirs": [f"{_SALT_DEVICE_ROOT}/states"],
        "grains_dirs": [f"{_SALT_DEVICE_ROOT}/grains"],
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


# Effective-model keys that are image/identity metadata, not salt formulas.
_NON_STATE_KEYS = {"osbakery", "device", "options", "role"}


def _available_formulas(states_root: Path) -> set[str]:
    """Top-level salt formulas present in the states tree.

    A formula is ``<name>.sls`` or ``<name>/init.sls`` — a bare directory
    without init.sls (e.g. batocera/ holding only base/, arcade/) is NOT a
    `state.apply <name>` target, so it's excluded.
    """
    out: set[str] = set()
    if states_root.is_dir():
        for p in states_root.iterdir():
            if p.is_dir() and (p / "init.sls").is_file():
                out.add(p.name)
            elif p.suffix == ".sls" and p.stem != "top":
                out.add(p.stem)
    return out


def _states_to_apply(ctx: "BuildContext", states_root: Path) -> list[str]:
    """Salt states to apply = the pillar's top-level keys that have a matching
    formula (e.g. pillar `batocera` → state `batocera`), preserving order.
    """
    avail = _available_formulas(states_root)
    keys = [k for k in (ctx.effective_model or {})
            if k not in _NON_STATE_KEYS and k in avail]
    from builds.orchestrator import order_formulas
    return order_formulas(keys)


def _stage_salt_roots(ctx: "BuildContext", system: Path) -> tuple[int, int, list[str]]:
    """Bake the salt states (file_roots) + rendered pillar (pillar_roots) onto
    the userdata partition so masterless ``salt-call --local`` has them.

    The baked state ``top.sls`` applies the formulas named by the pillar's
    top-level keys (batocera / salt / alloy / …). Returns
    (state_files, pillar_files, states_to_apply).
    """
    states_src = Path(settings.SALT_STATES_ROOT)
    states_dst = system / "opt/salt/states"
    pillar_dst = system / "opt/salt/pillar"

    # Merge (don't rmtree): the batocera package overlay already placed its own
    # custom state module at <root>/states/batocera.py — wiping the dir would
    # delete it. The gedu .sls file_roots tree layers on top.
    if states_src.is_dir():
        shutil.copytree(states_src, states_dst, dirs_exist_ok=True)
    else:
        states_dst.mkdir(parents=True, exist_ok=True)

    # State top = the pillar's top-level keys that have a matching formula.
    apply = _states_to_apply(ctx, states_src)
    (states_dst / "top.sls").write_text(
        yaml.safe_dump({"base": {"*": apply}}, default_flow_style=False)
    )

    if pillar_dst.exists():
        shutil.rmtree(pillar_dst)
    pillar_dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(ctx.pillar_path.glob("*")):
        if f.is_file():
            shutil.copy2(f, pillar_dst / f.name)

    n_states = sum(1 for _ in states_dst.rglob("*") if _.is_file())
    n_pillar = sum(1 for _ in pillar_dst.rglob("*") if _.is_file())
    return n_states, n_pillar, apply


# Salt file_roots use leading-underscore dirs (`_grains`, `_modules`, …) that
# normally require `saltutil.sync_*`. The batocera package instead loads .py
# modules directly from un-underscored dirs via module_dirs/states_dirs/
# grains_dirs (see _write_minion_conf). Copy the vendored gedu custom modules
# into those same dirs so they load at minion startup, before the first state
# run — merging with (not clobbering) the package's own modules.
_EXTMOD_MAP = {
    "_grains": "grains", "_modules": "modules", "_states": "states",
    "_utils": "utils", "_renderers": "renderers",
}


def _stage_extension_modules(system: Path) -> dict[str, int]:
    """Copy gedu custom modules from file_roots `_X/` into `<root>/X/`."""
    states_src = Path(settings.SALT_STATES_ROOT)
    staged: dict[str, int] = {}
    for under, plain in _EXTMOD_MAP.items():
        src = states_src / under
        if not src.is_dir():
            continue
        dst = system / "opt" / "salt" / plain
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in src.glob("*.py"):
            shutil.copy2(f, dst / f.name)
            n += 1
        if n:
            staged[plain] = n
    return staged


def _append_custom_sh(system: Path, services: list[str], apply: list[str]) -> None:
    """Idempotent first-boot hook: enable services, then apply the pillar-keyed
    states masterless via ``salt-call --local state.apply <key>``.
    """
    custom = system / "custom.sh"
    existing = custom.read_text() if custom.exists() else ""
    if _CUSTOM_MARKER in existing:
        return
    block = [_CUSTOM_MARKER, "if [ ! -f /userdata/system/.osbakery-provisioned ]; then"]
    block.append("  [ -x /userdata/system/bin/salt-init-minion ] && /userdata/system/bin/salt-init-minion || true")
    for svc in services:
        block.append(f"  batocera-services enable {svc} 2>/dev/null || true")
        block.append(f"  batocera-services start {svc} 2>/dev/null || true")
    # Sync the custom salt modules baked into file_roots (_grains, _modules,
    # _states, _returners, _utils, …) into the minion's extmods cache BEFORE
    # applying states. Custom grains (machine_model, usb_devices) load at minion
    # startup, so without this first-boot sync the grain-dependent states would
    # run with those grains absent. Runs on-device (real hardware), not at bake.
    block.append(
        "  /userdata/system/bin/salt-call --local saltutil.sync_all refresh=True "
        ">> /userdata/system/opt/salt/run/sync.log 2>&1 || true"
    )
    # Apply each pillar-keyed state masterless (the salt-call wrapper already
    # points at /userdata/system/opt/salt/conf, which has the local roots).
    for state in apply:
        block.append(
            f"  /userdata/system/bin/salt-call --local state.apply {state} "
            f">> /userdata/system/opt/salt/run/apply-{state}.log 2>&1 || true"
        )
    block.append("  touch /userdata/system/.osbakery-provisioned")
    block.append("fi")
    header = existing if existing.startswith("#!") else "#!/bin/bash\n" + existing
    custom.write_text(header.rstrip() + "\n\n" + "\n".join(block) + "\n")
    custom.chmod(0o755)


_SARCH = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}


def _find_squashfs(boot_mnt: Path) -> Path | None:
    """Locate the batocera root squashfs on the (FAT) boot partition."""
    cands = [boot_mnt / "boot" / "batocera", boot_mnt / "batocera"]
    cands += [p for p in boot_mnt.rglob("batocera*") if p.is_file()]
    for c in cands:
        try:
            with c.open("rb") as fh:
                if fh.read(4) in (b"hsqs", b"sqsh"):
                    return c
        except OSError:
            pass
    return None


def _apply_salt_local(ctx, build, boot_part, userdata: Path, apply: list[str]) -> None:
    """Run `salt-call --local state.apply <key>` at bake time, capturing output.

    Chroots into the batocera squashfs root (overlay; only /userdata persists,
    bound to the SHARE) and runs the bundled onedir salt-call per pillar-key
    state, emitting each step's output into the build log.
    """
    if not apply or boot_part is None:
        return
    guest = (getattr(getattr(ctx.build.hardware_target, "architecture", None), "slug", "") or "").lower()
    sarch = _SARCH.get(guest)
    if not sarch:
        _emit(build, "salt-apply", f"Unknown arch '{guest}' — skipping bake-time apply.",
              level="warning")
        return

    work = ctx.work_dir
    bootmnt, sqroot, root = work / "bootp", work / "sqroot", work / "chroot"
    up, wk = work / "ov/up", work / "ov/wk"
    mounts: list[Path] = []
    try:
        for d in (bootmnt, sqroot, root, up, wk):
            d.mkdir(parents=True, exist_ok=True)
        ls._mount(str(boot_part), bootmnt, opts=["-o", "ro"])
        mounts.append(bootmnt)
        sqfs = _find_squashfs(bootmnt)
        if not sqfs:
            _emit(build, "salt-apply",
                  "Batocera squashfs root not found on boot partition — "
                  "skipping bake-time apply (states will run on first boot).",
                  level="warning")
            return
        ls._sh(["mount", "-t", "squashfs", "-o", "loop,ro", str(sqfs), str(sqroot)])
        mounts.append(sqroot)
        ls._sh(["mount", "-t", "overlay", "overlay", "-o",
                f"lowerdir={sqroot},upperdir={up},workdir={wk}", str(root)])
        mounts.append(root)
        # /userdata = the SHARE (writes persist into the image); pseudo-fs binds.
        (root / "userdata").mkdir(exist_ok=True)
        ls._sh(["mount", "--bind", str(userdata), str(root / "userdata")])
        mounts.append(root / "userdata")
        for spec, dst in [(["--bind", "/dev"], root / "dev"),
                          (["--bind", "/dev/pts"], root / "dev/pts"),
                          (["-t", "proc", "proc"], root / "proc"),
                          (["-t", "sysfs", "sys"], root / "sys"),
                          (["-t", "tmpfs", "tmpfs"], root / "run")]:
            dst.mkdir(parents=True, exist_ok=True)
            ls._sh(["mount", *spec, str(dst)])
            mounts.append(dst)
        # Foreign arch (ARM image on x86 worker): rely on the registered
        # qemu-<arch>-static binfmt handler; copy the static binary in too.
        if sarch != os.uname().machine:
            q = Path(f"/usr/bin/qemu-{sarch}-static")
            if q.exists():
                (root / "usr/bin").mkdir(parents=True, exist_ok=True)
                shutil.copy2(q, root / "usr/bin" / q.name)
        try:
            shutil.copy2("/etc/resolv.conf", root / "etc/resolv.conf")
        except OSError:
            pass

        saltcall = f"/userdata/system/bin/{sarch}/salt/salt-call"
        _emit(build, "salt-apply",
              f"Bake-time masterless apply (arch={sarch}) of: {', '.join(apply)}.")
        ok = True
        for state in apply:
            cp = ls._sh(["chroot", str(root), saltcall,
                         "--config-dir=/userdata/system/opt/salt/conf",
                         "--local", "--state-output=mixed", "--retcode-passthrough",
                         "state.apply", state],
                        check=False, capture=True)
            rc = getattr(cp, "returncode", 1)
            out = ((cp.stdout or "") + (cp.stderr or "")).strip()
            if rc < 0 and not out:
                # Killed by a signal at startup (no output) — almost always a
                # custom grain/module probing hardware absent in the bake chroot.
                _emit(build, "salt-apply",
                      f"state.apply {state}: salt-call killed (signal {-rc}) during "
                      "grain/module load — likely a custom grain probing hardware "
                      "not present in the bake chroot. This formula applies "
                      "on-device at first boot (custom.sh → "
                      "/userdata/system/opt/salt/run/apply-*.log), not at bake.",
                      level="warning", returncode=rc, state=state)
            else:
                _emit_cmd(build, "salt-apply", f"salt-call --local state.apply {state}", cp)
            ok = ok and rc == 0
        if ok:
            # States applied at bake → first-boot hook skips re-applying.
            (userdata / "system" / ".osbakery-provisioned").write_text("baked\n")
    finally:
        for m in reversed(mounts):
            ls._sh(["umount", "-lf", str(m)], check=False)


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
        n_states, n_pillar, apply = _stage_salt_roots(ctx, system)
        _emit(build, "salt-roots",
              f"Staged file_roots ({n_states} state files) + pillar_roots "
              f"({n_pillar} files) under {_SALT_DEVICE_ROOT}/{{states,pillar}}. "
              f"State top applies pillar keys: {', '.join(apply) or '(none matched a formula)'}.",
              state_files=n_states, pillar_files=n_pillar, states_applied=apply)
        extmods = _stage_extension_modules(system)
        if extmods:
            _emit(build, "salt-roots",
                  "Copied custom modules to the minion module path: "
                  + ", ".join(f"{v}→/opt/salt/{k}" for k, v in extmods.items())
                  + ".", extmods=extmods)
        _write_minion_conf(ctx, system)
        opts = ctx.build.option_values or {}
        master = getattr(settings, "SALT_MASTER_URL", "") or opts.get("salt_master", "")
        _emit(build, "salt-roots",
              f"Wrote minion conf: id={opts.get('minion_id') or opts.get('hostname') or build.label}, "
              f"{'master=' + master if master else 'file_client=local'}.")
        _append_custom_sh(system, _SERVICES, apply)
        _emit(build, "provision",
              f"First-boot custom.sh: enable {', '.join(_SERVICES)} + "
              f"salt-call --local state.apply [{', '.join(apply) or 'none'}].")
        ls.write_model_file(system, "osbakery/model.yaml", ctx.effective_model)
        # Run the pillar-keyed states masterless at bake time (chroot into the
        # batocera squashfs root) so the apply output lands in the build log.
        _apply_salt_local(ctx, build, _boot, userdata, apply)
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
