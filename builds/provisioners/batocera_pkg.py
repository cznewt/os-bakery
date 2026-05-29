"""Batocera provisioner — bootstrap-install salt from a package URL, then apply
the salt states (which configure the repos + install the rest) and enable the
services, all at bake.

Batocera is buildroot (no apt/chroot-exec); apps are pacman packages. So baking =
grow + mount the image's userdata (SHARE) partition, stage the salt file_roots /
pillar + minion config, seed salt.minion-id, then chroot into the batocera
squashfs root and: ``pacman -U <salt-package-url>`` (so salt-call exists),
``salt-call --local state.apply`` per pillar-keyed formula (the ``batocera``
formula sets up the private repos; the others install alloy / zerotier / … via
their own pkg.installed), and ``batocera-services enable`` per service. Nothing
is deferred to first boot — the image boots fully provisioned (batocera
auto-starts the enabled services).

The salt apply uses a qemu-emulated chroot for foreign-arch (ARM) images, so the
salt package URL + the repos it configures + DNS must be reachable from the
worker at bake time.
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

# Salt is bootstrap-installed at bake from a package URL (``pacman -U`` of
# settings.SALT_PACKAGE_URLS[arch] or the per-build ``salt_package_url`` option)
# so salt-call exists to apply the states. Everything else (alloy, zerotier, …)
# is installed by those states' own pkg.installed once the salt run configures
# the repos (the bootstrap URL is the public repo — fine for demos + tests).
# Services we make sure are enabled after the apply (belt-and-suspenders: the
# package batoexec + the formulas' service.running normally handle this, but the
# batoexec's `start` may not fire cleanly in the bake chroot).
_SERVICES = ["salt_minion", "alloy", "textfile_collector"]

# Extra SHARE headroom (MiB) for the bake-time package installs (salt + alloy +
# zerotier + the pacman cache). The fresh batocera SHARE is tiny and self-grows
# on first boot, so we grow it here. Tune if installs hit ENOSPC.
_GROW_MIB = 1024


def _emit(build, phase, message, level="info", **data):
    # NUL (U+0000) in salt-call/pacman output is stripped centrally in
    # BuildEvent.save() (Postgres jsonb/text can't store it).
    BuildEvent.objects.create(build=build, phase=phase, message=message, level=level, data=data)


def _free_mib(path: Path) -> tuple[int, int]:
    """(free_MiB, total_MiB) on the filesystem holding ``path``."""
    try:
        st = os.statvfs(path)
        return (st.f_bavail * st.f_frsize) // (1024 * 1024), \
               (st.f_blocks * st.f_frsize) // (1024 * 1024)
    except OSError:
        return 0, 0


def _emit_cmd(build, phase, label, cp) -> None:
    """Emit a command result with its captured output.

    salt-call writes the state-result table + ``Summary for local`` to STDOUT
    and its ``[ERROR] …`` logging (e.g. the benign batocera-settings-get probes
    that fail in the bake chroot) to STDERR. Keep stdout as the primary tail so
    the actual run result is visible, with only a short stderr tail appended —
    otherwise a flood of repeated stderr lines truncates the summary away.
    """
    so = (getattr(cp, "stdout", "") or "").strip()
    se = (getattr(cp, "stderr", "") or "").strip()
    rc = getattr(cp, "returncode", 0)
    parts = []
    if so:
        parts.append(so[-4000:])
    if se:
        # Collapse the repeated identical [ERROR] lines so they don't drown the
        # result, then keep a short tail.
        seen, dedup = set(), []
        for ln in se.splitlines():
            key = ln.strip()
            if key in seen and key.startswith("[ERROR"):
                continue
            seen.add(key)
            dedup.append(ln)
        parts.append("---- stderr ----\n" + "\n".join(dedup)[-1500:])
    _emit(build, phase, f"{label} (rc={rc})",
          level="warning" if rc else "info",
          returncode=rc, output_tail="\n\n".join(parts))


# Effective-model keys that are image/identity metadata, not salt formulas.
_NON_STATE_KEYS = {"osbakery", "device", "options", "role"}


_SARCH = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}

# Custom grains that probe real hardware through native libraries (libusb for
# usb_devices, …). Salt runs every grain module at salt-call startup, so under
# qemu-user emulation in the bake chroot these SIGILL and kill the whole run
# before any state applies — and a SIGILL can't be caught, nor does salt's
# grains_blacklist help (it filters output *after* the function runs). No baked
# formula needs them (the batocera/salt/alloy states branch only on core grains
# like os_family), and they load fine on real hardware at first boot, so we drop
# them from the bake-time grains path only. Add a name here if a new grain
# crashes the bake the same way.
_BAKE_UNSAFE_GRAINS = {"batocera_resolution", "usb_devices"}

# Ephemeral (chroot tmpfs/overlay) home for the bake-only salt config — never
# lands on the persistent userdata partition, so it can't ship in the image.
_BAKE_CONF_ROOT = "/run/osbakery-bake"


def _write_bake_conf(root: Path, system: Path) -> tuple[str, list[str]]:
    """Stage a bake-only minion config that excludes hardware-probing grains.

    Mirrors the on-device minion conf (same file_roots / pillar_roots / module
    dirs so states + pillar still resolve) but points ``grains_dirs`` at a
    curated copy of the staged grains with the ``_BAKE_UNSAFE_GRAINS`` dropped,
    and forces masterless. Written under the chroot's tmpfs so it is discarded
    with the bake. Returns (in-chroot ``--config-dir``, excluded grain names).
    """
    src_conf = system / "opt/salt/conf/minion"
    conf = yaml.safe_load(src_conf.read_text()) if src_conf.is_file() else {}
    conf["grains_dirs"] = [f"{_BAKE_CONF_ROOT}/grains"]
    conf["file_client"] = "local"
    conf.pop("master", None)  # never reach for a master during the bake

    base = root / _BAKE_CONF_ROOT.lstrip("/")
    conf_dir, grains_dir = base / "conf", base / "grains"
    conf_dir.mkdir(parents=True, exist_ok=True)
    grains_dir.mkdir(parents=True, exist_ok=True)
    (conf_dir / "minion").write_text(
        yaml.safe_dump(conf, default_flow_style=False, sort_keys=False)
    )

    # The misc-salt package ships custom grains in _grains + states/_grains;
    # copy all but the hardware-probing ones into the bake grains dir.
    excluded: list[str] = []
    for gd in (system / "opt/salt/_grains", system / "opt/salt/states/_grains"):
        if not gd.is_dir():
            continue
        for f in sorted(gd.glob("*.py")):
            if f.stem in _BAKE_UNSAFE_GRAINS:
                if f.stem not in excluded:
                    excluded.append(f.stem)
                continue
            shutil.copy2(f, grains_dir / f.name)
    return f"{_BAKE_CONF_ROOT}/conf", excluded


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


def _salt_pkg_url(ctx: "BuildContext", sarch: str) -> str | None:
    """Parametrisable URL of the misc-salt package to bootstrap-install at bake:
    the per-build ``salt_package_url`` option wins, else
    ``settings.SALT_PACKAGE_URLS[<sarch>]`` (sarch = aarch64 / x86_64).
    """
    opts = ctx.build.option_values or {}
    if opts.get("salt_package_url"):
        return opts["salt_package_url"]
    return (getattr(settings, "SALT_PACKAGE_URLS", {}) or {}).get(sarch)


def _download(url: str, dest: Path) -> str | None:
    """Fetch ``url`` → ``dest`` host-side (native, HTTP/1.1, follows redirects).

    Done on the host rather than via pacman inside the chroot because pacman's
    libcurl negotiates HTTP/2 and the stream dies mid-transfer under qemu on
    large files. Returns an error string on failure — including a non-zstd body
    (e.g. an auth/login HTML page from an SSO redirect) — else None.
    """
    import urllib.error
    import urllib.request
    attempts, last = 3, "no attempt"
    for _ in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "osbakery-bake"})
            with urllib.request.urlopen(req, timeout=180) as r:
                expected = int(r.headers.get("Content-Length") or 0)
                with open(dest, "wb") as f:
                    shutil.copyfileobj(r, f)
            got = dest.stat().st_size
            if expected and got != expected:  # flaky proxy short-closed the body
                last = f"truncated: got {got} of {expected} bytes"
                continue
            with open(dest, "rb") as f:
                if f.read(4) != b"\x28\xb5\x2f\xfd":  # zstd magic
                    last = "not a zstd archive (auth/HTML page?)"
                    continue
            return None
        except (urllib.error.URLError, OSError) as exc:
            last = str(exc)
    return f"{last} (after {attempts} attempts)"


def _seed_minion_id(ctx: "BuildContext", system: Path) -> str:
    """Seed ``salt.minion-id`` into batocera.conf before the salt run so the
    minion + alloy service pick up the right id. The repos themselves are
    configured by the ``batocera`` formula during the apply, not here.
    """
    opts = ctx.build.option_values or {}
    minion_id = (opts.get("minion_id") or opts.get("hostname")
                 or ctx.build.label or f"osbakery-{ctx.build.id}")
    conf = system / "batocera.conf"
    kept = [ln for ln in (conf.read_text().splitlines() if conf.is_file() else [])
            if not ln.startswith("salt.minion-id=")]
    kept.append(f"salt.minion-id={minion_id}")
    conf.write_text("\n".join(kept) + "\n")
    return minion_id


def _write_pillar(ctx: "BuildContext", system: Path) -> list[str]:
    """Write the rendered pillar into the misc-salt package's pillar tree.

    The package's ``pillar/top.sls`` maps the ``batocera`` pillar file to ``*``,
    and its states ``top.sls`` is pillar-driven (applies the ``states:`` list on
    highstate). So one ``pillar/batocera.sls`` holding the effective model's
    state-data keys + a ``states:`` list is all the bake needs to inject; the
    states themselves come from the package. Returns the states list.
    """
    model = ctx.effective_model or {}
    data = {k: v for k, v in model.items() if k not in _NON_STATE_KEYS}
    # batocera first (it configures the pacman repos the rest install from).
    states = (["batocera"] if "batocera" in data else []) + \
             [k for k in data if k != "batocera"]
    pillar = {**data, "states": states}
    pdir = system / "opt/salt/pillar"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "top.sls").write_text("base:\n  '*':\n    - batocera\n")
    (pdir / "batocera.sls").write_text(
        yaml.safe_dump(pillar, default_flow_style=False, sort_keys=False))
    return states


def _apply_salt_local(ctx, build, boot_part, userdata: Path) -> None:
    """Install salt + apply the states in the batocera chroot at bake time.

    Chroots into the batocera squashfs root (overlay; only /userdata persists,
    bound to the SHARE), ``pacman -U`` installs misc-salt (its state tree + conf
    come with it), then runs the bundled onedir salt-call: ``state.apply
    batocera`` (configures the repos), then ``state.highstate`` (the pillar's
    ``states:`` list). Output is streamed into the build log.
    """
    if boot_part is None:
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
        env = ["/usr/bin/env", "PATH=/usr/sbin:/usr/bin:/sbin:/bin:/userdata/system/bin"]

        # Bootstrap: install misc-salt from its package URL. The package owns the
        # state tree (salt://{batocera,salt,alloy,zerotier,…}) and its install
        # hook writes the minion conf (file_roots→states, pillar_roots→pillar) —
        # so we install onto a clean tree (we no longer stage states, which would
        # collide) and just supply the pillar. Fetch host-side (native, HTTP/1.1):
        # pacman's in-chroot download negotiates HTTP/2 and the flaky proxy
        # resets the stream under qemu on large files.
        url = _salt_pkg_url(ctx, sarch)
        if not url:
            _emit(build, "salt-apply",
                  "No salt package URL (set the `salt_package_url` option or "
                  f"SALT_PACKAGE_URLS[{sarch}]) — cannot install salt at bake.",
                  level="error")
            return
        pkg_host = userdata / "system" / "pacman" / "osbakery-salt-bootstrap.pkg.tar.zst"
        pkg_chroot = "/userdata/system/pacman/osbakery-salt-bootstrap.pkg.tar.zst"
        pkg_host.parent.mkdir(parents=True, exist_ok=True)
        err = _download(url, pkg_host)
        if err:
            _emit(build, "salt-apply",
                  f"Could not fetch salt package {url}: {err} — cannot install "
                  "salt at bake.", level="error")
            return
        _emit(build, "salt-apply",
              f"Downloaded salt package ({pkg_host.stat().st_size // (1024 * 1024)} MiB) "
              f"from {url}; installing with pacman -U.")
        inst = ls._sh(["chroot", str(root), *env, "pacman", "-U", "--noconfirm", pkg_chroot],
                      check=False, capture=True)
        _emit_cmd(build, "salt-apply", f"pacman -U {pkg_chroot}", inst)
        try:
            pkg_host.unlink()
        except OSError:
            pass
        if not (userdata / "system" / "bin" / sarch / "salt" / "salt-call").is_file():
            _emit(build, "salt-apply",
                  f"Installing salt from {url} did not produce {saltcall} — "
                  "cannot apply states at bake.", level="error",
                  returncode=getattr(inst, "returncode", 1))
            return

        # Bake-only conf from the package's minion conf, with grains_dirs pointed
        # at a curated copy (hardware-probing grains like batocera_resolution
        # dropped) so the aarch64 salt-call doesn't SIGILL under qemu.
        bake_confdir, excluded = _write_bake_conf(root, userdata / "system")
        if excluded:
            _emit(build, "salt-apply",
                  "Excluded hardware-probing grains from the bake chroot "
                  f"(they SIGILL under qemu; load on-device at first boot): "
                  f"{', '.join(excluded)}.", excluded_grains=excluded)

        # Apply the batocera formula first (writes pacman.conf so the repos
        # exist), then the pillar-driven highstate (installs + configures the
        # rest from those repos).
        ok = True
        for sc in (["state.apply", "batocera"], ["state.highstate"]):
            cp = ls._sh(["chroot", str(root), saltcall, f"--config-dir={bake_confdir}",
                         "--local", "--state-output=full", "--retcode-passthrough", *sc],
                        check=False, capture=True)
            rc = getattr(cp, "returncode", 1)
            out = ((cp.stdout or "") + (cp.stderr or "")).strip()
            if rc < 0 and not out:
                _emit(build, "salt-apply",
                      f"salt-call {' '.join(sc)}: killed (signal {-rc}) during "
                      "grain/module load. Hardware-probing grains are already "
                      f"excluded at bake ({', '.join(sorted(_BAKE_UNSAFE_GRAINS))}); "
                      "add the offending one to _BAKE_UNSAFE_GRAINS.",
                      level="warning", returncode=rc)
            else:
                _emit_cmd(build, "salt-apply", "salt-call --local " + " ".join(sc), cp)
            ok = ok and rc == 0
        # Enable the batocera services (belt-and-suspenders — the package batoexec
        # + the formulas' service.running normally handle this; `start` is a
        # runtime-only action left to batocera's boot-time service manager).
        for svc in _SERVICES:
            cp = ls._sh(["chroot", str(root), *env, "batocera-services", "enable", svc],
                        check=False, capture=True)
            _emit_cmd(build, "salt-apply", f"batocera-services enable {svc}", cp)
        _emit(build, "salt-apply",
              f"Bake-time provisioning complete (states_ok={ok}; enabled "
              f"{', '.join(_SERVICES)}).", states_ok=ok, services=_SERVICES)
    finally:
        for m in reversed(mounts):
            ls._sh(["umount", "-lf", str(m)], check=False)


def provision(ctx: "BuildContext") -> bool:
    build = ctx.build
    userdata = ctx.work_dir / "userdata"
    userdata.mkdir(exist_ok=True)
    _emit(build, "provision",
          "Batocera: staging salt roots + repo config, then installing salt and "
          "applying states at bake.", backend="batocera_pkg")

    # The fresh batocera image ships a tiny SHARE partition (it self-grows on
    # first boot); the bake-time package installs (salt + alloy + zerotier +
    # pacman cache) don't fit. So grow the image file + SHARE partition here,
    # before mounting, then resize its fs.
    grow_by = _GROW_MIB * 1024 * 1024
    img_before = ctx.target_image.stat().st_size
    _emit(build, "grow",
          f"Growing image {img_before // (1024*1024)} → "
          f"{(img_before+grow_by) // (1024*1024)} MiB (+{_GROW_MIB} MiB for "
          "bake-time installs).", grow_mib=_GROW_MIB)
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
                  f"SHARE is {fstype} (no online grow) — installs may still ENOSPC.",
                  level="warning")
        ls._mount(str(share_part), userdata)
        mounted.append(userdata)
        free0, total = _free_mib(userdata)
        _emit(build, "mount", f"Mounted SHARE at userdata: {free0}/{total} MiB free.",
              free_mib=free0, total_mib=total)

        system = userdata / "system"
        system.mkdir(parents=True, exist_ok=True)

        # The misc-salt package owns the state tree + minion conf (installed in
        # _apply_salt_local). os-bakery just supplies the data: seed the minion
        # id and write the rendered pillar into the package's pillar tree.
        minion_id = _seed_minion_id(ctx, system)
        states = _write_pillar(ctx, system)
        _emit(build, "salt-roots",
              f"Seeded salt.minion-id={minion_id}; wrote pillar/batocera.sls "
              f"(states: {', '.join(states) or '(none)'}). Salt + the state tree "
              "are installed from the misc-salt package at bake.",
              minion_id=minion_id, states=states)
        ls.write_model_file(system, "osbakery/model.yaml", ctx.effective_model)
        # Install salt + apply the states in the chroot (squashfs root). No
        # first-boot hook — the image is provisioned at bake.
        _apply_salt_local(ctx, build, _boot, userdata)
        free_end, _ = _free_mib(userdata)
        _emit(build, "provision",
              f"Batocera provisioned: salt installed + states applied + model.yaml "
              f"staged. {free_end} MiB free on SHARE.",
              backend="batocera_pkg", free_mib=free_end)
        return True
    finally:
        for path in reversed(mounted):
            ls._sh(["umount", "-lf", str(path)], check=False)
        if lo:
            ls._sh(["losetup", "-d", lo], check=False)
