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

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from builds.models import BuildEvent
from builds.provisioners import local_salt as ls

if TYPE_CHECKING:
    from builds.orchestrator import BuildContext

log = logging.getLogger(__name__)

_ASSISTANT = "proxmox-auto-install-assistant"


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
    g.append(f"root_password = {_toml_str(opts.get('root_password') or 'changeme')}")
    if keys:
        g.append("root_ssh_keys = [" + ", ".join(_toml_str(k) for k in keys) + "]")

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
    disk.append("disk_list = [" + _toml_str(target_disk or "sda") + "]")

    return "\n".join(g + [""] + net + [""] + disk) + "\n"


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

    out_iso = ctx.work_dir / f"{build.id}.iso"
    _emit(build, "proxmox", "Preparing auto-install ISO (prepare-iso --fetch-from iso).")
    cp = ls._sh([
        "proxmox-auto-install-assistant", "prepare-iso", str(ctx.target_image),
        "--fetch-from", "iso", "--answer-file", str(answer_path),
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
