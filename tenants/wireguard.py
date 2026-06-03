"""WireGuard keypair generation — shells out to ``wg``.

``wg`` ships with wireguard-tools (installed into the web image). We generate a
fresh private key (``wg genkey``) and derive its public key (``wg pubkey``). The
caller persists the result as a :class:`tenants.models.WireguardIdentity`; the
bake then splices the private key into the pillar via
:func:`tenants.models.splice_wireguard_identities`, while the public key is what
you authorize as a ``[Peer]`` on the WireGuard server/hub.

Mirrors :mod:`tenants.zerotier` (which shells out to ``zerotier-idtool``).
"""

from __future__ import annotations

import shutil
import subprocess


class WgError(RuntimeError):
    """wg is missing or failed."""


class WgRegisterError(RuntimeError):
    """Registering a client on the wg-easy controller failed."""


def register_client(*, url: str, password: str, name: str,
                    username: str = "admin",
                    timeout: int = 20) -> dict[str, str]:
    """Register (create) a client on a wg-easy **v15** controller; return its config.

    wg-easy v15 uses HTTP Basic Auth (admin user + password) and a different API
    than v14: ``POST /api/client`` ({name, expiresAt}) mints the keypair + assigns
    the next overlay IP (idempotent by name); ``GET /api/client/{id}/configuration``
    returns the wg-quick config. The node thus boots already-authorized on the
    controller — the WireGuard analogue of :func:`tenants.zerotier.register_member`.

    Returns ``{private_key, public_key, address, server_public_key,
    preshared_key, endpoint, allowed_ips, client_id}``.
    """
    import re

    import requests

    if not (url and password and name):
        raise WgRegisterError("wg-easy url/password/name required.")
    base = url.rstrip("/")
    auth = (username or "admin", password)
    try:
        def _clients() -> dict:
            r = requests.get(f"{base}/api/client", auth=auth, timeout=timeout)
            if r.status_code == 401:
                raise WgRegisterError(
                    "wg-easy auth failed (HTTP 401) — check the admin "
                    "username/password (controller token).")
            r.raise_for_status()
            return {c.get("name"): c for c in r.json()}

        clients = _clients()
        if name not in clients:
            cr = requests.post(f"{base}/api/client", auth=auth,
                               json={"name": name, "expiresAt": None},
                               timeout=timeout)
            if cr.status_code not in (200, 201):
                raise WgRegisterError(
                    f"wg-easy create client failed (HTTP {cr.status_code}): "
                    f"{cr.text[:200]}")
            clients = _clients()
        client = clients.get(name)
        if not client:
            raise WgRegisterError(f"wg-easy client '{name}' missing after create.")
        cid = client["id"]
        conf = requests.get(f"{base}/api/client/{cid}/configuration",
                            auth=auth, timeout=timeout).text
    except requests.RequestException as exc:
        raise WgRegisterError(f"wg-easy API error: {exc}") from exc

    def _f(pat: str) -> str:
        m = re.search(pat, conf, re.MULTILINE)
        return m.group(1).strip() if m else ""

    priv = _f(r"^PrivateKey\s*=\s*(.+)$")
    if not priv:
        raise WgRegisterError("wg-easy returned a config without a PrivateKey.")
    return {
        "private_key": priv,
        "public_key": client.get("publicKey", ""),
        "address": str(client.get("ipv4Address") or "") or _f(r"^Address\s*=\s*(.+)$"),
        "server_public_key": _f(r"^PublicKey\s*=\s*(.+)$"),
        "preshared_key": _f(r"^PresharedKey\s*=\s*(.+)$"),
        "endpoint": _f(r"^Endpoint\s*=\s*(.+)$"),
        "allowed_ips": _f(r"^AllowedIPs\s*=\s*(.+)$"),
        "client_id": cid,
    }


def get_client_config(*, url: str, password: str, name: str,
                     username: str = "admin",
                     timeout: int = 20) -> str:
    """Fetch a wg-easy **v15** client's full wg-quick config by name (Basic Auth).

    The registration only persists the node's private key, but a working tunnel
    also needs the server-issued PresharedKey — so the Windows/init scripts fetch
    the complete ``.conf`` live from the controller.
    """
    import requests

    if not (url and password and name):
        raise WgRegisterError("wg-easy url/password/name required.")
    base = url.rstrip("/")
    auth = (username or "admin", password)
    try:
        r = requests.get(f"{base}/api/client", auth=auth, timeout=timeout)
        if r.status_code == 401:
            raise WgRegisterError(
                "wg-easy auth failed (HTTP 401) — check the admin "
                "username/password (controller token).")
        r.raise_for_status()
        client = {c.get("name"): c for c in r.json()}.get(name)
        if not client:
            raise WgRegisterError(f"wg-easy has no client named '{name}'.")
        return requests.get(f"{base}/api/client/{client['id']}/configuration",
                            auth=auth, timeout=timeout).text
    except requests.RequestException as exc:
        raise WgRegisterError(f"wg-easy API error: {exc}") from exc


def _wg() -> str:
    path = shutil.which("wg")
    if not path:
        raise WgError(
            "wg not found on PATH — install wireguard-tools "
            "(it ships in the os-bakery web image)."
        )
    return path


def generate_keypair() -> dict[str, str]:
    """Generate a fresh WireGuard keypair.

    Returns ``{"private_key", "public_key"}`` — base64, as wg-quick expects.
    ``wg pubkey`` reads the private key on stdin and derives the public key.
    """
    wg = _wg()
    try:
        priv = subprocess.run(
            [wg, "genkey"],
            check=True, capture_output=True, text=True, timeout=60,
        ).stdout.strip()
        pub = subprocess.run(
            [wg, "pubkey"], input=priv + "\n",
            check=True, capture_output=True, text=True, timeout=60,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise WgError(
            f"wg keypair generation failed: {exc.stderr or exc}"
        ) from exc
    if not (priv and pub):
        raise WgError("wg produced an empty keypair.")
    return {"private_key": priv, "public_key": pub}
