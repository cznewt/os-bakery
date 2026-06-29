---
name: add-wg-node
description: >-
  Add a node to the os-bakery fleet (web UI at http://10.50.20.226:8000/nodes/)
  modeled on an existing sibling node, and register it on the wg-easy WireGuard
  hub so the device joins the 10.13.13.0/24 overlay. Use when asked to add a
  roaming/personal device (Windows laptop, Batocera handheld, etc.) for someone
  to the GeekEdu fleet and put it on WireGuard — e.g. "add gameedu-roam-fanda-
  windows-laptop same as <sibling>, register to wireguard".
---

# Add a fleet node + register it to WireGuard (os-bakery)

os-bakery's node registry lives at **http://10.50.20.226:8000/nodes/** (prod).
Adding a device is two steps in that UI: **create the Node**, then **Add
WireGuard** (which, for a controller-backed peer, registers the node on the live
wg-easy hub and mints its keypair + overlay IP). The device then pulls its config
from the node's `.ps1` / `.conf` / QR link.

This is a **production write** that also creates a real peer on the live VPN hub.
Only run it when the user has explicitly asked to add the node + register it.

## TL;DR — use the helper

```bash
.claude/skills/add-wg-node/add_wg_node.sh \
  --name gameedu-roam-<person>-<device> \
  --like <existing-sibling-node-slug-or-id> \
  [--peer gedu-prg]            # gedu-prg = public (roaming, default); gedu-prg-lan = on-LAN
```

It copies cluster/preset/hardware_target from `--like`, creates the node,
registers it on the peer's wg-easy controller, then prints the config (private
key redacted) and the device hand-off links. It is safe to re-run (wg-easy is
idempotent by client name).

## Naming convention (get this right)

- **`--name` = the node slug = the SALT minion id** — full, e.g.
  `gameedu-roam-fanda-windows-laptop`. The master's `top.sls` globs and the
  os-bakery ext_pillar key on this (`/pillar/<slug>`).
- **`--hostname` = the WireGuard / wg-easy client name** — SHORT, the device's
  actual host name; **required** (no clean rule, so the helper won't guess). A
  Windows laptop is `<person>-windows` (kubik-windows, fanda-windows) — drop the
  `-laptop`; a handheld/phone is its own short name.
- The helper pins `parameters.salt.id = <slug>` so the salt id is the full slug
  even though `Node.minion_id` (the wg-easy client) is the short hostname. **Do
  NOT** suffix `-init` or use the full slug as the hostname. (As of the
  effective_model patch, salt.id *defaults* to the slug — the pin is now belt-and-
  suspenders, and still correct against an un-redeployed instance.)

## Pick the right `--like` template (the "same as X" trap)

Match the **device type**, not just the person. The fleet names nodes
`gameedu-roam-<person>-<device>`, but the cluster/preset/target come from the
*device*:

| New device | Template sibling | cluster / preset / hardware_target |
|---|---|---|
| `*-windows-laptop` | `gameedu-roam-benik-windows-laptop` / `…-kili-windows-laptop` | `gedu-computer-windows` / `windows-workstation` / `pc-amd64` |
| `*-batocera-laptop` | `gameedu-roam-kubik-batocera-laptop` | (roam cluster) / `batocera-notebook` / `pc-amd64` |
| `*-rg353*` handheld | `gameedu-roam-newt-rg353v` | (roam cluster) / `batocera-handheld` / `rg353*` |

> ⚠️ "same as kubik" usually means the **roam-device pattern**, not literally
> cloning kubik — `gameedu-roam-kubik-batocera-laptop` is a *Batocera* node, so
> for a Windows laptop use a `*-windows-laptop` sibling instead. IDs (cluster=24,
> preset=13, target=4 today) drift; always derive them from a live sibling via
> `--like`, never hardcode.

## Which peer

Both target the same `10.13.13.0/24` overlay (server key `OO9cdJM…`, wg-easy v15):

- **`gedu-prg`** → `lab.geekedu.eu:51820` — public WAN endpoint. Use for
  **roaming** devices (laptops/handhelds that leave the LAN). **Default.**
- **`gedu-prg-lan`** → `10.50.61.17:51820` — use only for devices that live on
  the gedu LAN.

The controller assigns the next free overlay IP automatically.

## Hand-off to the device

After registration, the node page exposes (also printed by the script):

- **Windows:** `…/nodes/<pk>/wireguard/ps1/` — elevated PowerShell that installs
  WireGuard + the tunnel as an auto-start service.
- **Android:** `…/nodes/<pk>/wireguard/android/` — scannable QR.
- **Anything:** `…/nodes/<pk>/wireguard/conf/` — raw wg-quick `.conf` (carries the
  private key; fetched live from the controller so it includes the PresharedKey).

## Doing it by hand (when the helper doesn't fit)

The endpoints (Django, **CSRF-protected, no login**):

1. `POST /nodes/new/` — `name`, `slug`, `hostname`, `cluster`, `preset`,
   `hardware_target` (numeric ids), empty `parameters_yaml`. 302 → `/nodes/<pk>/`.
2. `POST /nodes/<pk>/wireguard/add/` — `wireguard_peer=<slug>`. When the peer has
   a wg-easy controller this calls `register_client(name=node.minion_id)` → the
   hub mints the keypair + IP + PSK; os-bakery stores a `WireguardIdentity` and
   writes `wireguard.interfaces[]` into the node params.

**CSRF gotcha:** GET the form page and POST with the **same cookie jar**
(`curl -c jar -b jar` on every call) and the `csrfmiddlewaretoken` from *that*
response. Rotating the jar between GET and POST → HTTP 403.

## Model reference (code)

- `tenants/models.py` — `Node` (cluster⊕preset⊕hardware_target⊕params →
  `effective_model`), `WireguardIdentity`, `Integration` (type `wg_easy`),
  `splice_wireguard_identities`.
- `catalog/models.py` — `WireguardPeer` (endpoint/public_key/allowed_ips/
  `address_pool`/`controller`).
- `tenants/wireguard.py` — `register_client` / `get_client_config` (wg-easy v15
  HTTP Basic API).
- `osbakery/views.py` — `node_create`, `node_clone`, `node_wireguard_add`,
  `node_wireguard_ps1/conf/android`.
