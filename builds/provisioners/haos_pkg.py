"""HAOS provisioner — first-boot config injected onto the boot partition.

HAOS is an appliance: add-ons are Supervisor-managed Docker containers, so they
can't be file-overlaid like batocera packages. What we CAN bake by mounting the
image's partitions:

* boot partition (`hassos-boot`, FAT): a `CONFIG/network/` NetworkManager
  keyfile (Wi-Fi/static) and an `authorized_keys` for the debug SSH (port
  22222) — both read by HAOS on first boot.
* add-on repository pre-seed + a HA backup `.tar` to restore on first boot
  (the supported way to ship preinstalled add-ons like salt/alloy) — scaffolded
  here; the backup is provided out-of-band and dropped on the data partition.

Reads build option_values: wifi_ssid / wifi_psk / wifi_country,
ssh_authorized_keys, hostname, addon_repos, ha_backup_url.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from builds.models import BuildEvent
from builds.provisioners import local_salt as ls

if TYPE_CHECKING:
    from builds.orchestrator import BuildContext

log = logging.getLogger(__name__)


def _emit(build, phase, message, level="info", **data):
    BuildEvent.objects.create(build=build, phase=phase, message=message, level=level, data=data)


def _nm_wifi_keyfile(ssid: str, psk: str, country: str) -> str:
    sec = ""
    if psk:
        sec = f"\n[wifi-security]\nkey-mgmt=wpa-psk\npsk={psk}\n"
    return (
        "[connection]\nid=osbakery-wifi\ntype=wifi\n"
        f"\n[wifi]\nmode=infrastructure\nssid={ssid}\n{sec}"
        "\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n"
    )


def provision(ctx: "BuildContext") -> bool:
    build = ctx.build
    opts = build.option_values or {}
    boot = ctx.work_dir / "haos-boot"
    boot.mkdir(exist_ok=True)
    _emit(build, "provision", "HAOS: injecting first-boot config onto the boot partition.",
          backend="haos_pkg")

    lo: str | None = None
    mounted: list[Path] = []
    try:
        lo, parts = ls._attach_loop(ctx.target_image)
        # hassos-boot is the FAT partition; HAOS reads CONFIG/ + authorized_keys there.
        _root, boot_part = ls._classify_partitions(parts)
        if boot_part is None:
            _emit(build, "provision", "No FAT boot partition found on the HAOS image.",
                  level="warning")
            return False
        ls._mount(str(boot_part), boot, opts=["-o", "umask=0022"])
        mounted.append(boot)

        did = []
        # SSH authorized_keys for the debug SSH (port 22222).
        keys = opts.get("ssh_authorized_keys") or opts.get("ssh_authorized_key") or ""
        if isinstance(keys, list):
            keys = "\n".join(keys)
        if keys.strip():
            (boot / "authorized_keys").write_text(keys.strip() + "\n")
            did.append("authorized_keys")
        # Wi-Fi via a NetworkManager keyfile under CONFIG/network/.
        ssid = opts.get("wifi_ssid")
        if ssid:
            netdir = boot / "CONFIG" / "network"
            netdir.mkdir(parents=True, exist_ok=True)
            (netdir / "osbakery-wifi").write_text(
                _nm_wifi_keyfile(ssid, opts.get("wifi_psk", ""), opts.get("wifi_country", "DE"))
            )
            (netdir / "osbakery-wifi").chmod(0o600)
            did.append("wifi")

        # Phase 2 (needs your backup .tar): add-on repo pre-seed + first-boot
        # restore. Recorded so it's visible the value was set.
        backup = opts.get("ha_backup_url")
        repos = opts.get("addon_repos")
        if backup or repos:
            _emit(build, "provision",
                  "HAOS add-on automation (repos/backup-restore) is scaffolded — "
                  "supply a HA backup .tar to bake preinstalled add-ons.",
                  level="info", addon_repos=repos or "", ha_backup_url=backup or "")

        _emit(build, "provision",
              f"HAOS: baked {', '.join(did) or 'no first-boot config (none provided)'}.",
              backend="haos_pkg")
        return bool(did)
    finally:
        for path in reversed(mounted):
            ls._sh(["umount", "-lf", str(path)], check=False)
        if lo:
            ls._sh(["losetup", "-d", lo], check=False)
