"""ZeroTier identity generation — shells out to ``zerotier-idtool``.

``zerotier-idtool`` ships with ``zerotier-one`` (installed into the web image).
We generate a fresh identity (``identity.secret`` + ``identity.public``) and read
back the 10-hex member address from the public identity. The caller persists the
result as a :class:`tenants.models.ZerotierIdentity`; the bake then splices it
into the pillar via :func:`tenants.models.splice_zerotier_identities`.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


# Known ZeroTier networks a node can join from the node-detail UI. Add a row
# when a new network is provisioned on the controller.
ZEROTIER_NETWORKS: list[dict[str, str]] = [
    {"network_id": "a57fdfffb0c77a31", "name": "craftama-infrastructure",
     "cidr": "10.70.0.0/24"},
    {"network_id": "a57fdfffb03ef7e9", "name": "nxlabs-geekedu",
     "cidr": "10.50.20.0/24"},
]


class IdtoolError(RuntimeError):
    """zerotier-idtool is missing or failed."""


def _idtool() -> str:
    path = shutil.which("zerotier-idtool")
    if not path:
        raise IdtoolError(
            "zerotier-idtool not found on PATH — install zerotier-one "
            "(it ships in the os-bakery web image)."
        )
    return path


def generate_identity() -> dict[str, str]:
    """Generate a fresh ZeroTier identity.

    Returns ``{"member_id", "public_key", "secret_key"}`` — ``member_id`` is the
    10-hex node address (the leading field of ``identity.public``), suitable for
    pre-authorizing on a controller.
    """
    idtool = _idtool()
    with tempfile.TemporaryDirectory(prefix="osbakery-zt-") as tmp:
        sec = Path(tmp) / "identity.secret"
        pub = Path(tmp) / "identity.public"
        try:
            subprocess.run(
                [idtool, "generate", str(sec), str(pub)],
                check=True, capture_output=True, text=True, timeout=120,
            )
        except subprocess.CalledProcessError as exc:
            raise IdtoolError(
                f"zerotier-idtool generate failed: {exc.stderr or exc}"
            ) from exc
        secret_key = sec.read_text().strip()
        public_key = pub.read_text().strip()

    member_id = public_key.split(":", 1)[0] if public_key else ""
    if not member_id:
        raise IdtoolError("zerotier-idtool produced an empty identity.")
    return {
        "member_id": member_id,
        "public_key": public_key,
        "secret_key": secret_key,
    }


class RegistrationError(RuntimeError):
    """Registering/authorizing a member on the ZeroTier controller failed."""


def register_member(*, url: str, token: str, network_id: str, member_id: str,
                    name: str, public_key: str = "", authorize: bool = True) -> None:
    """Register a member on ZeroTier Central (https://my.zerotier.com).

    Pre-provisions the member before the device ever connects, via
    ``POST {url}/api/v1/network/<network_id>/member/<member_id>``: sets the
    member ``name``, authorizes it, and — crucially — seeds ``config.identity``
    with the device's full public identity (``identity.public`` contents,
    ``<member_id>:0:<hexpubkey>``) so the controller binds this address to the
    baked keypair instead of waiting for a live join. ``url`` + ``token`` come
    from the tenant's :class:`tenants.models.Integration` (url is the API base,
    e.g. ``https://my.zerotier.com``). Raises :class:`RegistrationError` on any
    failure; the caller treats it best-effort.
    """
    import requests

    if not (url and token):
        raise RegistrationError("ZeroTier controller url/token not configured.")
    base = url.rstrip("/")
    endpoint = f"{base}/api/v1/network/{network_id}/member/{member_id}"
    config: dict = {"authorized": bool(authorize)}
    if public_key:
        # The full public identity ("<member_id>:0:<pub>") — lets ZT Central
        # pre-seed this member with the baked keypair before it connects.
        config["identity"] = public_key
    payload: dict = {"name": name, "config": config}
    try:
        resp = requests.post(
            endpoint, json=payload, timeout=30,
            headers={"Authorization": f"token {token}",
                     "Content-Type": "application/json"},
        )
    except requests.RequestException as exc:
        raise RegistrationError(f"ZeroTier API request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise RegistrationError(
            f"ZeroTier API {resp.status_code}: {resp.text[:300]}"
        )
