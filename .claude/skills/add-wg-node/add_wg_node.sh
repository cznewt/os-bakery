#!/usr/bin/env bash
# os-bakery — add a fleet node modeled on an existing sibling, then register it
# on the wg-easy WireGuard hub (controller mints the keypair + overlay IP + PSK).
#
# Drives the public web UI (Django, CSRF-protected, no login). The wg-easy
# registration is keyed by the node's minion-id (= hostname), so re-running is
# safe — the controller is idempotent by client name.
#
# Usage:
#   ./add_wg_node.sh --name gameedu-roam-fanda-windows-laptop \
#                    --like gameedu-roam-benik-windows-laptop \
#                    [--peer gedu-prg] [--hostname <name>-init] \
#                    [--base http://10.50.20.226:8000]
#
#   --name  slug+name of the new node (convention: gameedu-roam-<person>-<device>).
#   --like  slug (or unique substring) OR numeric id of an existing node to copy
#           cluster / preset / hardware_target from. Pick a sibling of the SAME
#           device type (a *-windows-laptop for a Windows laptop, a *-rg353* for a
#           handheld, …) — NOT just any node with a similar person name.
#   --peer  WireguardPeer slug. gedu-prg = public lab.geekedu.eu:51820 (roaming,
#           default); gedu-prg-lan = on-LAN 10.50.61.17:51820.
#   --hostname  REQUIRED. The device HOSTNAME = the wg-easy/WireGuard client name
#               (SHORT, e.g. kubik-windows, fanda-windows). A windows laptop is
#               <person>-windows (drop the -laptop). NB the SALT minion id is the
#               full --name slug, NOT this.
set -euo pipefail

BASE="http://10.50.20.226:8000"; PEER="gedu-prg"; NAME=""; LIKE=""; HOST=""
while [ $# -gt 0 ]; do case "$1" in
  --name) NAME="$2"; shift 2;;
  --like) LIKE="$2"; shift 2;;
  --peer) PEER="$2"; shift 2;;
  --base) BASE="${2%/}"; shift 2;;
  --hostname) HOST="$2"; shift 2;;
  -h|--help) sed -n '2,30p' "$0"; exit 0;;
  *) echo "unknown arg: $1" >&2; exit 2;;
esac; done
[ -n "$NAME" ] && [ -n "$LIKE" ] || { echo "need --name and --like (see --help)" >&2; exit 2; }
# Naming convention: WG/wg-easy client name = the device HOSTNAME (short); the
# SALT minion id = the full node slug ($NAME). The short hostname is a human
# choice with no clean rule (kubik-windows, fanda-windows, kubik-flip2-android),
# so REQUIRE it — don't guess (a windows laptop is <person>-windows, dropping
# the -laptop).
[ -n "$HOST" ] || { echo "need --hostname: the device's SHORT host name = the wg-easy client name (e.g. kubik-windows, fanda-windows). The salt id is the full --name slug." >&2; exit 2; }
# Pin salt.id = full slug so the effective model + ext_pillar key on the slug
# (resolve_node prefers parameters.salt.id), not on the short hostname. (Redundant
# once the salt.id-defaults-to-slug model patch ships, but harmless + works now.)
PARAMS_YAML="salt:
  id: $NAME"

JAR="$(mktemp)"; LIST="$(mktemp)"; DET="$(mktemp)"; HDR="$(mktemp)"; CONF="$(mktemp)"
trap 'rm -f "$JAR" "$LIST" "$DET" "$HDR" "$CONF"' EXIT
# Shared cookie jar (-c AND -b) so the csrftoken cookie matches the form token.
g() { curl -fsS -c "$JAR" -b "$JAR" -m 30 -e "$BASE/nodes/" "$@"; }
# grep -m1 (not `... | head -1`): head closing the pipe early would SIGPIPE grep
# and, under `set -o pipefail`, abort the whole script (exit 141).
csrf() { grep -oE -m1 'name="csrfmiddlewaretoken" value="[^"]+"' "$1" \
         | sed -E 's/.*value="([^"]+)".*/\1/'; }

# 1) Resolve the --like template node id.
g "$BASE/nodes/" -o "$LIST"
LIKE_ID="$(python3 - "$LIST" "$LIKE" <<'PY'
import re,sys
s=open(sys.argv[1]).read(); like=sys.argv[2]
if like.isdigit(): print(like); sys.exit()
exact=[]; sub=[]
for nid,txt in re.findall(r'href="/nodes/(\d+)/"[^>]*>\s*([^<]+)', s):
    t=txt.strip()
    (exact if t==like else sub if like in t else []).append(nid)
print((exact or sub or [""])[0])
PY
)"
[ -n "$LIKE_ID" ] || { echo "no node matches --like '$LIKE'" >&2; exit 1; }

# 2) Read cluster / preset / hardware_target from the template's edit form.
g "$BASE/nodes/$LIKE_ID/" -o "$DET"
read -r CLUSTER PRESET TARGET < <(python3 - "$DET" <<'PY'
import re,sys
s=open(sys.argv[1]).read()
def sel(name):
    m=re.search(r'name="%s".*?</select>'%name, s, re.S)
    o=m and re.search(r'<option value="(\d+)"[^>]*\bselected', m.group(0))
    return o.group(1) if o else ""
print(sel("cluster"), sel("preset"), sel("hardware_target"))
PY
)
[ -n "$CLUSTER" ] && [ -n "$PRESET" ] && [ -n "$TARGET" ] \
  || { echo "could not read cluster/preset/target from template #$LIKE_ID" >&2; exit 1; }
echo ">> template #$LIKE_ID -> cluster=$CLUSTER preset=$PRESET hardware_target=$TARGET"

# 3) Create the node (empty params; the WG step fills wireguard.interfaces).
g "$BASE/nodes/" -o "$LIST"; TOK="$(csrf "$LIST")"
g -D "$HDR" -o /dev/null \
  --data-urlencode "csrfmiddlewaretoken=$TOK" \
  --data-urlencode "name=$NAME" --data-urlencode "slug=$NAME" \
  --data-urlencode "hostname=$HOST" \
  --data-urlencode "cluster=$CLUSTER" --data-urlencode "preset=$PRESET" \
  --data-urlencode "hardware_target=$TARGET" \
  --data-urlencode "parameters_yaml=$PARAMS_YAML" --data-urlencode "tags=" --data-urlencode "notes=" \
  "$BASE/nodes/new/"
PK="$(grep -i '^location:' "$HDR" | grep -oE '/nodes/[0-9]+/' | tr -dc 0-9)"
[ -n "$PK" ] || { echo "create failed (no redirect) — name may already exist." >&2; exit 1; }
echo ">> created node #$PK  $NAME  (salt id $NAME, wg/hostname $HOST)"

# 4) Register on the wg-easy hub via the peer. Controller mints keypair+IP+PSK.
g "$BASE/nodes/$PK/" -o "$DET"; TOK="$(csrf "$DET")"
g -o /dev/null \
  --data-urlencode "csrfmiddlewaretoken=$TOK" \
  --data-urlencode "wireguard_peer=$PEER" \
  "$BASE/nodes/$PK/wireguard/add/"

# 5) Pull the config (live from the controller) and print the hand-off links.
if g "$BASE/nodes/$PK/wireguard/conf/" -o "$CONF" 2>/dev/null; then
  echo ">> tunnel config (PrivateKey redacted):"
  sed -E 's/(PrivateKey *= *).*/\1<REDACTED>/' "$CONF" | sed 's/^/   /'
fi
echo
echo ">> done. Hand-off links for the device:"
echo "   Windows installer : $BASE/nodes/$PK/wireguard/ps1/      (run elevated)"
echo "   Android QR        : $BASE/nodes/$PK/wireguard/android/"
echo "   Raw wg-quick conf : $BASE/nodes/$PK/wireguard/conf/"
