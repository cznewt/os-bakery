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
