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
# when a new network is provisioned on the controller. ``org`` is the ZTNET
# organization id that owns the network (the controller is org-scoped, and our
# two networks live in different orgs) — used to build the member endpoint.
ZEROTIER_NETWORKS: list[dict[str, str]] = [
    {"network_id": "a57fdfffb0c77a31", "network_name": "craftama-infrastructure",
     "cidr": "10.70.0.0/24", "org": "cm6ovuefh0003mt017mqtr8wp"},
    {"network_id": "a57fdfffb03ef7e9", "network_name": "nxlabs-geekedu",
     "cidr": "10.50.20.0/24", "org": "cm6ovurq40005mt01316kv1wi"},
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


def register_member(*, url: str, token: str, org: str, network_id: str,
                    member_id: str, name: str, authorize: bool = True) -> None:
    """Register + authorize a member on a self-hosted ZTNET controller.

    Pre-provisions the member before the device connects, via the ZTNET
    org-scoped API::

        POST {url}/api/v1/org/<org>/network/<network_id>/member/<member_id>
        x-ztnet-auth: <token>
        {"name": ..., "authorized": true}

    Per the ZTNET docs, posting a member id that hasn't joined yet creates it on
    the controller (the device then connects as an already-authorized member; its
    baked identity is delivered separately via the salt pillar). ``url`` is the
    controller host (e.g. ``https://vpn.craftama.eu``) and ``org`` is the owning
    ZTNET organization id — both come from the Integration + network catalog.
    Raises :class:`RegistrationError` on failure; the caller treats it
    best-effort.
    """
    import requests

    if not (url and token and org):
        raise RegistrationError(
            "ZTNET controller url/token/org not configured."
        )
    base = url.rstrip("/")
    endpoint = (f"{base}/api/v1/org/{org}/network/{network_id}"
                f"/member/{member_id}")
    payload: dict = {"name": name, "authorized": bool(authorize)}
    try:
        resp = requests.post(
            endpoint, json=payload, timeout=30,
            headers={"x-ztnet-auth": token,
                     "Content-Type": "application/json"},
        )
    except requests.RequestException as exc:
        raise RegistrationError(f"ZTNET API request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise RegistrationError(
            f"ZTNET API {resp.status_code}: {resp.text[:300]}"
        )
