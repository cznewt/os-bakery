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

import yaml
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


def _is_qcow2(path: Path) -> bool:
    """True if the file starts with the qcow2 magic (QFI\\xfb)."""
    try:
        with path.open("rb") as fh:
            return fh.read(4) == b"QFI\xfb"
    except OSError:
        return False


# loop device -> (raw working copy, original qcow2 path) for images we had to
# convert to raw to loop-mount. _detach_loop repacks raw -> qcow2 on teardown.
_LOOP_QCOW2: dict[str, tuple[Path, Path]] = {}


def _attach_loop(img: Path, ctx: "BuildContext | None" = None,
                 grow_gib: int = 0) -> tuple[str, list[Path]]:
    """losetup -P the image, then wait for partition nodes to materialise.

    qcow2 images (Ubuntu/Debian cloud-img, HAOS .qcow2.xz) have no raw
    partition table for losetup to scan, so convert to a raw sibling first and
    attach that; _detach_loop repacks the raw back into the original qcow2 on
    teardown. ``grow_gib`` enlarges the backing file by that many GiB before
    attaching so a later growpart/resize2fs can expand the rootfs (cloud images
    ship a tiny rootfs that can't fit a bake-time salt install). Returns
    (loop_device, [partition_paths]). Raises if none appear.
    """
    attach = img
    raw: Path | None = None
    if _is_qcow2(img):
        raw = img.with_suffix(".raw.img")
        if ctx is not None:
            _emit(ctx.build, "prepare",
                  "Source is qcow2 — converting to raw to loop-mount.")
        _sh(["qemu-img", "convert", "-O", "raw", str(img), str(raw)])
        attach = raw
    if grow_gib:
        if ctx is not None:
            _emit(ctx.build, "prepare",
                  f"Growing image by {grow_gib} GiB headroom for the bake-time "
                  f"salt install.")
        _sh(["truncate", "-s", f"+{grow_gib}G", str(attach)])
    lo = _sh(["losetup", "-f", "-P", "--show", str(attach)], capture=True).stdout.strip()
    if raw is not None:
        _LOOP_QCOW2[lo] = (raw, img)
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


def _detach_loop(lo: str) -> None:
    """Detach a loop device from _attach_loop; if it was a converted qcow2,
    repack the modified raw back into the original qcow2 artifact."""
    _sh(["losetup", "-d", lo], check=False)
    entry = _LOOP_QCOW2.pop(lo, None)
    if entry is not None:
        raw, original = entry
        _sh(["qemu-img", "convert", "-O", "qcow2", str(raw), str(original)])
        raw.unlink(missing_ok=True)


def _grow_to_fill(lo: str, part: Path, ctx: "BuildContext | None" = None) -> None:
    """Grow ``part`` (an ext2/3/4 rootfs) into the free space added by
    _attach_loop(grow_gib=…). growpart relocates the GPT backup header and
    extends the partition; resize2fs then grows the filesystem. Best-effort —
    a layout with no trailing free space (root not last) just no-ops.
    """
    fstype = _sh(["blkid", "-o", "value", "-s", "TYPE", str(part)],
                 check=False, capture=True).stdout.strip()
    if fstype not in {"ext2", "ext3", "ext4"}:
        if ctx is not None:
            _emit(ctx.build, "grow",
                  f"root {part.name} is {fstype or '?'} (not ext*) — skipping grow.",
                  level="warning")
        return
    partnum = part.name.rsplit("p", 1)[-1]
    gp = _sh(["growpart", lo, partnum], check=False, capture=True)
    if ctx is not None:
        _emit(ctx.build, "grow", f"growpart {lo} {partnum}: "
              f"{(gp.stdout or gp.stderr or '').strip()[:200] or 'ok'}")
    _sh_optional(["partprobe", lo])
    _sh_optional(["udevadm", "settle", "--timeout=5"])
    _sh(["e2fsck", "-fy", str(part)], check=False)
    _sh(["resize2fs", str(part)], check=False)
    if ctx is not None:
        mib = int(_sh(["blockdev", "--getsize64", str(part)],
                      check=False, capture=True).stdout.strip() or "0") // (1024 * 1024)
        _emit(ctx.build, "grow", f"rootfs {part.name} now {mib} MiB.")


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


def write_model_file(root: Path, rel_path: str, model: dict) -> Path:
    """Write the effective model as YAML onto a mounted partition.

    ``root`` is the mountpoint, ``rel_path`` the destination relative to it
    (e.g. ``etc/osbakery/model.yaml``). Used by every provisioner so the merged
    device+cluster config physically travels with the baked image.
    """
    dst = root / rel_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(yaml.safe_dump(model or {}, default_flow_style=False,
                                  sort_keys=False))
    try:
        dst.chmod(0o644)
    except OSError:
        pass  # vfat / exfat can't chmod
    return dst


def _boot_mount_rel(rootfs: Path) -> str:
    """Where the image mounts its firmware/boot partition, per its own fstab.

    Returns a path relative to the rootfs (e.g. "boot/firmware" or "boot").
    Falls back to "boot/firmware" then "boot" if fstab is unreadable.
    """
    fstab = rootfs / "etc/fstab"
    try:
        for raw in fstab.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) >= 3 and "boot" in fields[1] and "vfat" in fields[2]:
                return fields[1].lstrip("/")
    except OSError:
        pass
    # No explicit vfat boot entry — prefer the bookworm layout if present.
    return "boot/firmware" if (rootfs / "boot/firmware").is_dir() else "boot"


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
    # Ubuntu/Debian cloud images symlink /etc/resolv.conf at a systemd-resolved
    # stub (../run/systemd/resolve/stub-resolv.conf) that dangles inside the
    # chroot, so a plain copy lands nowhere and apt/curl can't resolve. Replace
    # it with a real file. Skip the host's docker-embedded resolver (127.x,
    # unreachable from the chroot's resolver path) and fall back to public DNS.
    nameservers: list[str] = []
    try:
        for line in Path("/etc/resolv.conf").read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "nameserver" \
                    and not parts[1].startswith("127."):
                nameservers.append(parts[1])
    except OSError:
        pass
    nameservers = nameservers or ["1.1.1.1", "8.8.8.8"]
    resolv = rootfs / "etc/resolv.conf"
    resolv.parent.mkdir(parents=True, exist_ok=True)
    if resolv.is_symlink() or resolv.exists():
        resolv.unlink()
    resolv.write_text("".join(f"nameserver {ns}\n" for ns in nameservers))


# Masterless salt-call. Salt isn't in Debian/raspios default repos, so we add
# the official SaltProject repository (key + .sources) before installing, then
# apply the highstate against the baked-in local roots — no master.
_CHROOT_SALT_SCRIPT = r"""
set -ex
export DEBIAN_FRONTEND=noninteractive
if ! command -v salt-call >/dev/null 2>&1; then
  apt-get update
  apt-get install -y --no-install-recommends curl ca-certificates gnupg
  install -d -m 0755 /etc/apt/keyrings
  # The SaltProject key is ASCII-armored; apt's signed-by with a .pgp keyring
  # wants a binary (dearmored) keyring, else it rejects it as an "unsupported
  # filetype" and the repo is treated as unsigned. Dearmor on the way in.
  curl -fsSL https://packages.broadcom.com/artifactory/api/security/keypair/SaltProjectKey/public \
    | gpg --dearmor -o /etc/apt/keyrings/salt-archive-keyring.pgp
  curl -fsSL https://github.com/saltstack/salt-install-guide/releases/latest/download/salt.sources \
    -o /etc/apt/sources.list.d/salt.sources
  apt-get update
  apt-get install -y --no-install-recommends salt-minion
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
        lo, parts = _attach_loop(ctx.target_image, ctx, grow_gib=4)
        root_part, boot_part = _classify_partitions(parts)
        # Cloud images ship a ~2 GiB rootfs (designed to growpart on first
        # boot) — too small for a bake-time salt install. Grow it now into the
        # 4 GiB headroom added above.
        _grow_to_fill(lo, root_part, ctx)
        _mount(str(root_part), rootfs)
        mounted.append(rootfs)
        if boot_part is not None:
            # Mount the firmware/boot partition where the image's own fstab
            # expects it — raspios bookworm uses /boot/firmware, older images
            # and most others use /boot. Honour fstab so states that write
            # cmdline.txt / config.txt hit the right path.
            boot_rel = _boot_mount_rel(rootfs)
            boot_dst = rootfs / boot_rel
            # vfat can't chmod, so present files as 0644 / dirs 0755 up front so
            # salt's default mode-enforcement is a no-op. NB: vfat's file base is
            # 0777, so fmask must be 0133 (0777 & ~0133 = 0644) — a plain
            # umask=0022 would yield 0755 files and salt would still try (and
            # fail) to chmod to 0644.
            _mount(str(boot_part), boot_dst, opts=["-o", "fmask=0133,dmask=0022"])
            mounted.append(boot_dst)

        mounted.extend(_bind_pseudo(rootfs))

        if emulate:
            _install_qemu(rootfs, guest_arch)

        _stage_salt(ctx, rootfs)

        # Bake the merged device+cluster model onto the image for inspection.
        write_model_file(rootfs, "etc/osbakery/model.yaml", ctx.effective_model)
        _emit(build, "salt", "Wrote /etc/osbakery/model.yaml (effective model).")

        _emit(build, "salt", "Installing salt + running salt-call --local in chroot.")
        proc = subprocess.run(
            ["chroot", str(rootfs), "/bin/sh", "-ec", _CHROOT_SALT_SCRIPT],
            text=True, capture_output=True,
        )
        tail = ((proc.stdout or "") + (proc.stderr or ""))[-4000:]
        if proc.returncode != 0:
            _emit(build, "salt", "Masterless salt-call failed in chroot.",
                  level="error", returncode=proc.returncode, output_tail=tail)
            raise RuntimeError(
                f"chroot salt-call failed (rc={proc.returncode}); see event data."
            )
        _emit(build, "salt", "Masterless salt highstate applied.",
              backend="local_salt", output_tail=tail)
        return True
    finally:
        # Always tear down, in reverse order, best-effort.
        for path in reversed(mounted):
            _sh(["umount", "-lf", str(path)], check=False)
        if lo:
            _detach_loop(lo)
