"""Cloud-init provisioner — bake a NoCloud user-data that deploys salt.

For cloud-init-capable images (Ubuntu cloud-img / raspi / desktop), inject a
NoCloud seed whose user-data, on first boot: salt-bootstraps the minion
(Debian/Ubuntu), unpacks the baked /srv/salt (states + top) + /srv/pillar
(effective model) + a masterless /etc/salt/minion, and runs
``salt-call --local state.highstate`` — the recipe's states applied with no
master. Same deploy model as the Proxmox first-boot, delivered via cloud-init.

Seed location by image type:
* raspi (vfat boot partition): user-data/meta-data on the boot partition.
* cloud-img / generic: /var/lib/cloud/seed/nocloud/ on the root filesystem.
"""

from __future__ import annotations

import base64
import io
import logging
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

from builds.models import BuildEvent
from builds.provisioners import local_salt as ls

if TYPE_CHECKING:
    from builds.orchestrator import BuildContext

log = logging.getLogger(__name__)

_SALT_BOOTSTRAP = ("https://github.com/saltstack/salt-bootstrap/releases/"
                   "latest/download/bootstrap-salt.sh")


def _emit(build, phase, message, level="info", **data):
    BuildEvent.objects.create(build=build, phase=phase, message=message, level=level, data=data)


def _salt_payload_b64(ctx: "BuildContext") -> str:
    """tgz of /srv/salt (states + the build's top.sls) + /srv/pillar (effective
    model) + /etc/salt/minion (masterless), base64 for cloud-init write_files."""
    states_root = Path(settings.SALT_STATES_ROOT)
    minion = ("file_client: local\n"
              "file_roots:\n  base:\n    - /srv/salt\n"
              "pillar_roots:\n  base:\n    - /srv/pillar\n")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        if states_root.is_dir():
            tf.add(str(states_root), arcname="srv/salt")
        # The state top the orchestrator decided (recipe.salt_states).
        if ctx.top_path.exists():
            tf.add(str(ctx.top_path), arcname="srv/salt/top.sls")
        for f in sorted(ctx.pillar_path.glob("*")):
            if f.is_file():
                tf.add(str(f), arcname=f"srv/pillar/{f.name}")
        data = minion.encode()
        ti = tarfile.TarInfo("etc/salt/minion")
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    return base64.b64encode(buf.getvalue()).decode()


def _user_data(ctx: "BuildContext") -> str:
    payload = _salt_payload_b64(ctx)
    return f"""#cloud-config
# os-bakery: deploy salt masterless on first boot.
write_files:
  - path: /opt/osbakery/salt-payload.b64
    permissions: '0600'
    content: |
      {payload}
runcmd:
  - [sh, -c, "curl -fsSL -o /tmp/bootstrap-salt.sh {_SALT_BOOTSTRAP} || wget -qO /tmp/bootstrap-salt.sh {_SALT_BOOTSTRAP}"]
  - [sh, -c, "sh /tmp/bootstrap-salt.sh -X || true"]
  - [sh, -c, "base64 -d /opt/osbakery/salt-payload.b64 | tar -xzf - -C /"]
  - [sh, -c, "salt-call --local --state-output=mixed state.highstate >>/var/log/osbakery-salt.log 2>&1 || true"]
"""


def _meta_data(ctx: "BuildContext") -> str:
    opts = ctx.build.option_values or {}
    host = opts.get("hostname") or ctx.build.label or f"osbakery-{ctx.build.id}"
    return f"instance-id: osbakery-{ctx.build.id}\nlocal-hostname: {host}\n"


def _is_qcow2(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(4) == b"QFI\xfb"
    except OSError:
        return False


def provision(ctx: "BuildContext") -> bool:
    build = ctx.build
    # Ubuntu cloud images are qcow2 (despite the .img name) — losetup can't see
    # their partitions, so convert to raw, mount that, then convert back.
    src = ctx.target_image
    qcow2 = _is_qcow2(src)
    raw = ctx.work_dir / "ci-raw.img"
    img = src
    if qcow2:
        _emit(build, "cloud-init", "Source is qcow2 — converting to raw to mount.")
        ls._sh(["qemu-img", "convert", "-O", "raw", str(src), str(raw)])
        img = raw

    lo: str | None = None
    mounted: list[Path] = []
    try:
        lo, parts = ls._attach_loop(img)
        root_part, _boot = ls._classify_partitions(parts)
        user_data, meta_data = _user_data(ctx), _meta_data(ctx)

        # Always seed the rootfs NoCloud dir — cloud-init checks
        # /var/lib/cloud/seed/nocloud[-net] on every image (cloud-img, raspi,
        # generic), unlike the ESP/boot FAT which it ignores.
        root = ctx.work_dir / "ci-root"
        root.mkdir(exist_ok=True)
        ls._mount(str(root_part), root)
        mounted.append(root)
        for sub in ("var/lib/cloud/seed/nocloud", "var/lib/cloud/seed/nocloud-net"):
            seed = root / sub
            seed.mkdir(parents=True, exist_ok=True)
            (seed / "user-data").write_text(user_data)
            (seed / "meta-data").write_text(meta_data)
        where = "/var/lib/cloud/seed/nocloud[-net]"

        ls.write_model_file(root, "var/lib/osbakery-model.yaml", ctx.effective_model)
        _emit(build, "cloud-init",
              f"Baked NoCloud user-data at {where}: salt-bootstrap + masterless "
              f"state.highstate on first boot.",
              backend="cloud_init", output_tail=user_data[:1500])
    finally:
        for p in reversed(mounted):
            ls._sh(["umount", "-lf", str(p)], check=False)
        if lo:
            ls._sh(["losetup", "-d", lo], check=False)

    if qcow2:
        # Re-pack the modified raw back into the qcow2 artifact.
        ls._sh(["qemu-img", "convert", "-O", "qcow2", str(raw), str(src)])
        raw.unlink(missing_ok=True)
    return True
