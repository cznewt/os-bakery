"""Masterless local-salt provisioner.

This is the provisioner the orchestrator docstring always promised: instead of
installing a master-connected ``salt-minion`` (the packer-arm-tools path), it
loop-mounts the freshly-copied target image, chroots into the rootfs (emulated
via ``qemu-*-static`` + binfmt for a foreign architecture), and runs
``salt-call --local`` against the pillar + top the orchestrator already
rendered. No Salt master, no network registration — the device's config is
"committed" into the image at bake time.

It deliberately owns the brittle bits that packer-builder-arm got wrong in a
container:

* ``losetup -P`` then **wait for the partition nodes** (``udevadm settle`` +
  ``partprobe`` retry) — the loop-partition creation is asynchronous via udev,
  so mounting ``loopXp2`` immediately races and fails with ``exit 32``.
* For a foreign arch, copy ``qemu-<arch>-static`` into the rootfs and rely on a
  binfmt_misc entry registered with the ``F`` (fix-binary) flag, so the
  interpreter fd survives the chroot.

Everything runs in a ``try/finally`` so mounts + the loop device are always
torn down, even on failure.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

from builds.models import BuildEvent

if TYPE_CHECKING:
    from builds.orchestrator import BuildContext

log = logging.getLogger(__name__)

# OperatingSystem/HardwareTarget architecture slug -> qemu-user-static binary.
# Maps the *guest* arch to the emulator the host needs to run its binaries.
_QEMU_FOR_ARCH = {
    "arm64": "qemu-aarch64-static",
    "aarch64": "qemu-aarch64-static",
    "armhf": "qemu-arm-static",
    "armv7": "qemu-arm-static",
}

# Host arch tokens that mean "no emulation needed for x86 guests".
_NATIVE_X86 = {"x86_64", "amd64"}


def _emit(build, phase: str, message: str, level: str = "info", **data) -> None:
    BuildEvent.objects.create(build=build, phase=phase, message=message, level=level, data=data)


def _sh(cmd: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    log.debug("$ %s", " ".join(cmd))
    return subprocess.run(cmd, check=check, text=True,
                          capture_output=capture)


def _sh_optional(cmd: list[str]) -> None:
    """Run a best-effort command, ignoring a missing binary or non-zero exit.

    Used for ``udevadm``/``partprobe`` which help the loop-partition nodes
    appear but aren't installed in every worker image; their absence must not
    crash the bake (FileNotFoundError would otherwise propagate).
    """
    try:
        subprocess.run(cmd, check=False, text=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        log.debug("optional tool not present: %s", cmd[0])


def _guest_arch(ctx: "BuildContext") -> str:
    arch = getattr(ctx.build.hardware_target, "architecture", None)
    return (getattr(arch, "slug", "") or "").lower()


def _needs_emulation(guest_arch: str) -> bool:
    host = platform.machine().lower()
    if host in _NATIVE_X86 and guest_arch in {"amd64", "x86_64", ""}:
        return False
    if guest_arch in {"amd64", "x86_64"}:
        return False
    return guest_arch in _QEMU_FOR_ARCH


def _attach_loop(img: Path) -> tuple[str, list[Path]]:
    """losetup -P the image, then wait for partition nodes to materialise.

    Returns (loop_device, [partition_paths]). Raises if no partitions appear.
    """
    lo = _sh(["losetup", "-f", "-P", "--show", str(img)], capture=True).stdout.strip()
    name = Path(lo).name
    # Partition device nodes are created asynchronously by udev after the
    # PARTSCAN uevent. Settle + retry instead of racing into a mount.
    for attempt in range(40):
        _sh_optional(["udevadm", "settle", "--timeout=5"])
        parts = sorted(Path("/dev").glob(f"{name}p*"))
        if parts:
            return lo, parts
        # Nudge the kernel to re-read the partition table, then wait a beat.
        _sh_optional(["partprobe", lo])
        time.sleep(0.25)
    raise RuntimeError(f"no partition nodes appeared for {lo} after losetup -P")


def _classify_partitions(parts: list[Path]) -> tuple[Path, Path | None]:
    """Pick (root, boot) from the loop partitions by filesystem type.

    root = largest non-vfat filesystem; boot = a vfat partition if present.
    Good enough for the raspios/ubuntu/debian SBC images we cache (a small
    FAT firmware partition + an ext4 root).
    """
    boot: Path | None = None
    candidates: list[tuple[int, Path]] = []
    for p in parts:
        fstype = _sh(["blkid", "-o", "value", "-s", "TYPE", str(p)],
                     check=False, capture=True).stdout.strip()
        size = int(_sh(["blockdev", "--getsize64", str(p)],
                       check=False, capture=True).stdout.strip() or "0")
        if fstype in {"vfat", "fat", "msdos"} and boot is None:
            boot = p
        else:
            candidates.append((size, p))
    if not candidates:
        raise RuntimeError(f"no root filesystem among partitions: {parts}")
    root = max(candidates, key=lambda t: t[0])[1]
    return root, boot


def _mount(src: str, dst: Path, *, opts: list[str] | None = None) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    _sh(["mount", *(opts or []), src, str(dst)])


def _bind_pseudo(rootfs: Path) -> list[Path]:
    """Bind the host pseudo-filesystems the chroot needs; return mounted paths."""
    mounted: list[Path] = []
    specs = [
        (["--bind", "/dev"], rootfs / "dev"),
        (["--bind", "/dev/pts"], rootfs / "dev/pts"),
        (["-t", "proc", "proc"], rootfs / "proc"),
        (["-t", "sysfs", "sys"], rootfs / "sys"),
        (["-t", "tmpfs", "tmpfs"], rootfs / "run"),
    ]
    for opts, dst in specs:
        dst.mkdir(parents=True, exist_ok=True)
        _sh(["mount", *opts, str(dst)])
        mounted.append(dst)
    return mounted


def _install_qemu(rootfs: Path, guest_arch: str) -> Path | None:
    """Copy qemu-<arch>-static into the rootfs so emulated binaries can run.

    Relies on a binfmt_misc entry registered with the F (fix-binary) flag; the
    copied binary is what the kernel exec's for foreign ELF inside the chroot.
    """
    qemu = _QEMU_FOR_ARCH[guest_arch]
    src = shutil.which(qemu) or f"/usr/bin/{qemu}"
    if not Path(src).exists():
        raise RuntimeError(f"{qemu} not found on worker (install qemu-user-static)")
    dst = rootfs / "usr/bin" / qemu
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(src).resolve(), dst)
    return dst


def _stage_salt(ctx: "BuildContext", rootfs: Path) -> None:
    """Copy the salt states + rendered top.sls + pillar into the rootfs."""
    states_root = Path(settings.SALT_STATES_ROOT)
    srv_salt = rootfs / "srv/salt"
    srv_pillar = rootfs / "srv/pillar"
    if srv_salt.exists():
        shutil.rmtree(srv_salt)
    if srv_pillar.exists():
        shutil.rmtree(srv_pillar)
    shutil.copytree(states_root, srv_salt)
    shutil.copytree(ctx.pillar_path, srv_pillar)
    # The state top the orchestrator decided for this build wins over any
    # top.sls shipped in the states tree.
    shutil.copy2(ctx.top_path, srv_salt / "top.sls")
    # Give the chroot working DNS for the salt bootstrap / package install.
    resolv = rootfs / "etc/resolv.conf"
    if not resolv.exists() or resolv.stat().st_size == 0:
        try:
            shutil.copy2("/etc/resolv.conf", resolv)
        except OSError:
            pass


# Masterless salt-call: install salt if absent (apt, then the upstream
# bootstrap as a fallback), then apply the highstate against the local roots.
_CHROOT_SALT_SCRIPT = r"""
set -e
export DEBIAN_FRONTEND=noninteractive
if ! command -v salt-call >/dev/null 2>&1; then
  (apt-get update && apt-get install -y --no-install-recommends salt-minion) \
    || (curl -fsSL https://bootstrap.saltproject.io -o /tmp/bootstrap-salt.sh \
        && sh /tmp/bootstrap-salt.sh -X stable)
fi
# Masterless: read states/pillar from the baked-in local roots, no master.
salt-call --local --retcode-passthrough \
    --file-root=/srv/salt --pillar-root=/srv/pillar \
    state.apply
"""


def provision(ctx: "BuildContext") -> bool:
    """Bake the image masterless via a chrooted ``salt-call --local``.

    Returns True if salt ran (success or state failure surfaces as an
    exception); the orchestrator marks the build failed on any raise.
    """
    build = ctx.build
    guest_arch = _guest_arch(ctx)
    emulate = _needs_emulation(guest_arch)
    rootfs = ctx.work_dir / "rootfs"
    rootfs.mkdir(exist_ok=True)

    _emit(build, "salt",
          f"Masterless salt-call --local bake (arch={guest_arch or 'native'}, "
          f"emulated={emulate}).",
          backend="local_salt")

    lo: str | None = None
    mounted: list[Path] = []
    try:
        lo, parts = _attach_loop(ctx.target_image)
        root_part, boot_part = _classify_partitions(parts)
        _mount(str(root_part), rootfs)
        mounted.append(rootfs)
        if boot_part is not None:
            _mount(str(boot_part), rootfs / "boot")
            mounted.append(rootfs / "boot")

        mounted.extend(_bind_pseudo(rootfs))

        if emulate:
            _install_qemu(rootfs, guest_arch)

        _stage_salt(ctx, rootfs)

        _emit(build, "salt", "Running salt-call --local state.apply in chroot.")
        _sh(["chroot", str(rootfs), "/bin/sh", "-ec", _CHROOT_SALT_SCRIPT])
        _emit(build, "salt", "Masterless salt highstate applied.", backend="local_salt")
        return True
    finally:
        # Always tear down, in reverse order, best-effort.
        for path in reversed(mounted):
            _sh(["umount", "-lf", str(path)], check=False)
        if lo:
            _sh(["losetup", "-d", lo], check=False)
