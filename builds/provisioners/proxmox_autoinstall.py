"""Proxmox VE unattended-install provisioner.

Turns the official Proxmox VE installer ISO into a bootable *auto-install* ISO:
render an ``answer.toml`` from the bake options, then
``proxmox-auto-install-assistant prepare-iso … --fetch-from iso --answer-file``
embeds it so the installer runs with no prompts. Flash the output to USB, boot
the bare-metal node, and it installs Proxmox itself — the hypervisor deploy.

Reads build option_values: hostname, domain, root_password, email, timezone,
keyboard, country, filesystem, target_disk, ssh_authorized_keys, static_ip,
gateway, dns.
"""

from __future__ import annotations

import base64
import io
import logging
import shutil
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

from builds.models import BuildEvent
from builds.provisioners import local_salt as ls

if TYPE_CHECKING:
    from builds.orchestrator import BuildContext

log = logging.getLogger(__name__)

_ASSISTANT = "proxmox-auto-install-assistant"
_NON_STATE_KEYS = {"osbakery", "device", "options", "role", "vpn"}
_SALT_BOOTSTRAP = ("https://github.com/saltstack/salt-bootstrap/releases/"
                   "latest/download/bootstrap-salt.sh")


def _emit(build, phase, message, level="info", **data):
    BuildEvent.objects.create(build=build, phase=phase, message=message, level=level, data=data)


def _toml_str(v: str) -> str:
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_answer(opts: dict) -> str:
    """Build a Proxmox answer.toml from the bake options."""
    host = (opts.get("hostname") or "pve").strip()
    domain = (opts.get("domain") or "local").strip()
    fqdn = host if "." in host else f"{host}.{domain}"
    keys = opts.get("ssh_authorized_keys") or ""
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.splitlines() if k.strip()]

    g = ["[global]"]
    g.append(f"keyboard = {_toml_str(opts.get('keyboard') or 'en-us')}")
    g.append(f"country = {_toml_str(opts.get('country') or 'us')}")
    g.append(f"fqdn = {_toml_str(fqdn)}")
    g.append(f"mailto = {_toml_str(opts.get('email') or 'admin@' + domain)}")
    g.append(f"timezone = {_toml_str(opts.get('timezone') or 'UTC')}")
    g.append(f"root-password = {_toml_str(opts.get('root_password') or 'changeme')}")
    if keys:
        g.append("root-ssh-keys = [" + ", ".join(_toml_str(k) for k in keys) + "]")

    # Network: static when a CIDR is given, else DHCP (robust default).
    static = (opts.get("static_ip") or "").strip()
    if static:
        net = ["[network]", 'source = "from-answer"',
               f"cidr = {_toml_str(static)}"]
        if opts.get("gateway"):
            net.append(f"gateway = {_toml_str(opts['gateway'])}")
        net.append(f"dns = {_toml_str(opts.get('dns') or opts.get('gateway') or '1.1.1.1')}")
        # Match the first ethernet NIC by name; refine per-host if needed.
        net.append('filter.ID_NET_NAME = "*"')
    else:
        net = ["[network]", 'source = "from-dhcp"']

    disk = ["[disk-setup]",
            f"filesystem = {_toml_str(opts.get('filesystem') or 'ext4')}"]
    target_disk = (opts.get("target_disk") or "").strip()
    disk.append("disk-list = [" + _toml_str(target_disk or "sda") + "]")

    # Run our salt-bootstrap script on first boot, once the network is up.
    fb = ["[first-boot]", 'source = "from-iso"', 'ordering = "network-online"']

    return "\n".join(g + [""] + net + [""] + disk + [""] + fb) + "\n"


def _states_to_apply(ctx: "BuildContext", states_root: Path) -> list[str]:
    """Pillar top-level keys that have a matching formula (<name>.sls or
    <name>/init.sls) — the states applied masterless on the node."""
    avail: set[str] = set()
    if states_root.is_dir():
        for p in states_root.iterdir():
            if p.is_dir() and (p / "init.sls").is_file():
                avail.add(p.name)
            elif p.suffix == ".sls" and p.stem != "top":
                avail.add(p.stem)
    keys = [k for k in (ctx.effective_model or {})
            if k not in _NON_STATE_KEYS and k in avail]
    from builds.orchestrator import order_formulas
    return order_formulas(keys)


def _salt_payload_b64(ctx: "BuildContext", apply: list[str]) -> str:
    """Base64 tgz of /srv/salt (states + top), /srv/pillar (effective model),
    and /etc/salt/minion (masterless), unpacked at first boot."""
    states_root = Path(settings.SALT_STATES_ROOT)
    minion = ("file_client: local\n"
              "file_roots:\n  base:\n    - /srv/salt\n"
              "pillar_roots:\n  base:\n    - /srv/pillar\n")
    import yaml
    top = yaml.safe_dump({"base": {"*": apply}}, default_flow_style=False)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        if states_root.is_dir():
            tf.add(str(states_root), arcname="srv/salt")
        for f in sorted(ctx.pillar_path.glob("*")):
            if f.is_file():
                tf.add(str(f), arcname=f"srv/pillar/{f.name}")
        for arc, text in (("srv/salt/top.sls", top), ("etc/salt/minion", minion)):
            data = text.encode()
            ti = tarfile.TarInfo(arc)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return base64.b64encode(buf.getvalue()).decode()


def _first_boot_script(ctx: "BuildContext", apply: list[str]) -> str:
    """First-boot script: salt-bootstrap the minion, stage the baked local
    roots + pillar, and apply the pillar-keyed states masterless."""
    payload = _salt_payload_b64(ctx, apply)
    return f"""#!/usr/bin/env bash
set -eux
exec >>/var/log/osbakery-firstboot.log 2>&1
echo "[osbakery] installing salt-minion via salt-bootstrap"
curl -fsSL -o /tmp/bootstrap-salt.sh {_SALT_BOOTSTRAP} || \\
  wget -qO /tmp/bootstrap-salt.sh {_SALT_BOOTSTRAP}
sh /tmp/bootstrap-salt.sh -X || true   # -X: install only, no master/daemon
echo "[osbakery] staging local salt roots + pillar"
base64 -d > /tmp/osbk-salt.tgz <<'OSBK_B64'
{payload}
OSBK_B64
tar -xzf /tmp/osbk-salt.tgz -C /
echo "[osbakery] masterless highstate (states: {', '.join(apply) or 'none'})"
salt-call --local --state-output=mixed state.highstate || true
echo "[osbakery] first-boot provisioning done"
"""


def provision(ctx: "BuildContext") -> bool:
    build = ctx.build
    opts = build.option_values or {}
    if not shutil.which(_ASSISTANT):
        _emit(build, "provision",
              f"{_ASSISTANT} not in this worker — shipping the plain installer ISO.",
              level="warning")
        return False

    answer = _render_answer(opts)
    answer_path = ctx.work_dir / "answer.toml"
    answer_path.write_text(answer)
    _emit(build, "proxmox", "Rendered answer.toml for unattended install.",
          output_tail=answer)

    # Validate the answer file (surfaces schema errors in the log).
    _emit_cmd = ls._sh(["proxmox-auto-install-assistant", "validate-answer",
                        str(answer_path)], check=False, capture=True)
    out = ((_emit_cmd.stdout or "") + (_emit_cmd.stderr or "")).strip()
    _emit(build, "proxmox", f"validate-answer (rc={_emit_cmd.returncode})",
          level="warning" if _emit_cmd.returncode else "info", output_tail=out[-2000:])
    if _emit_cmd.returncode != 0:
        raise RuntimeError("Proxmox answer.toml failed validation; see event log.")

    # First-boot script: salt-bootstrap the minion + apply states masterless.
    apply = _states_to_apply(ctx, Path(settings.SALT_STATES_ROOT))
    fb_path = ctx.work_dir / "first-boot.sh"
    fb_path.write_text(_first_boot_script(ctx, apply))
    fb_path.chmod(0o755)
    _emit(build, "proxmox",
          f"First-boot: salt-bootstrap minion + masterless highstate "
          f"(states: {', '.join(apply) or 'none matched a formula'}).",
          states_applied=apply)

    out_iso = ctx.work_dir / f"{build.id}.iso"
    _emit(build, "proxmox", "Preparing auto-install ISO (prepare-iso --fetch-from iso).")
    cp = ls._sh([
        "proxmox-auto-install-assistant", "prepare-iso", str(ctx.target_image),
        "--fetch-from", "iso", "--answer-file", str(answer_path),
        "--on-first-boot", str(fb_path),
        "--output", str(out_iso),
    ], check=False, capture=True)
    tail = ((cp.stdout or "") + (cp.stderr or "")).strip()
    if cp.returncode != 0 or not out_iso.exists():
        _emit(build, "proxmox", "prepare-iso failed.", level="error",
              returncode=cp.returncode, output_tail=tail[-3000:])
        raise RuntimeError(f"prepare-iso failed (rc={cp.returncode}); see event log.")

    # Hand the auto-install ISO to pack/publish (raw .iso, no xz).
    ctx.target_image = out_iso
    _emit(build, "proxmox",
          f"Auto-install ISO ready: {out_iso.name} "
          f"({out_iso.stat().st_size // (1024*1024)} MiB).",
          backend="proxmox_autoinstall", output_tail=tail[-1500:])
    return True
