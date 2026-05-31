#!/usr/bin/env bash
#
# bake-node.sh — "bake" a LIVE Batocera node over SSH.
#
# Reproduces, on a RUNNING node, what os-bakery does to an image at build time
# (builds/provisioners/batocera_pkg.py) — reached over SSH instead of a chroot:
#
#     install the misc-salt package   (pacman -U <salt pkg url>)
#       -> [per-node] write the node's pillar to opt/salt/pillar/batocera.sls
#       -> salt-call --local state.apply batocera   (configures the repos)
#       -> salt-call --local state.highstate        (global: the pillar states)
#
# A per-node script (downloaded from a node's page, named <node>-init.sh) has
# that node's minion id + rendered pillar baked in below; the generic script
# leaves both empty and relies on the package's default (inert) pillar.
#
# Usage:
#     ./<node>-init.sh [--test] <node-ip-or-hostname>
#
#   --test, -t   Dry run: salt-call runs with test=True, so it previews the
#                changes (and the pillar) WITHOUT applying anything.
#
# Connects as root, preferring an SSH key from your agent and falling back to
# the Batocera default password ("linux") — the password path needs sshpass.
# Optional overrides via env:
#     MINION_ID=arcade-1 SALT_MASTER=salt.lan ./bake-node.sh 10.0.0.5
#     SALT_VERSION=3007.14-6 BATOCERA_REPO=https://utils.batocera.gameedu.eu
#     BATOCERA_ROOT_PASS=linux  TEST=1
#
set -euo pipefail

NODE=""
TEST="${TEST:-}"                         # non-empty -> dry run (salt test=True)
for arg in "$@"; do
    case "$arg" in
        --test|-t) TEST=1 ;;
        -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
        -*) echo "unknown option: $arg" >&2; exit 1 ;;
        *)  NODE="$arg" ;;
    esac
done
if [ -z "$NODE" ]; then
    echo "usage: $0 [--test] <node-ip-or-hostname>" >&2
    exit 1
fi

# Defaults mirror os-bakery's SALT_PACKAGE_URLS (compose.prod.yaml).
SALT_VERSION="${SALT_VERSION:-3007.14-6}"
BATOCERA_REPO="${BATOCERA_REPO:-https://utils.batocera.gameedu.eu}"
MINION_ID="${MINION_ID:-}"               # empty -> the node's own hostname
SALT_MASTER="${SALT_MASTER:-}"           # empty -> leave the package default
ROOT_PASS="${BATOCERA_ROOT_PASS:-linux}" # Batocera default root password

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"

echo ">> baking node '$NODE'  (salt $SALT_VERSION, repo $BATOCERA_REPO${TEST:+, TEST/dry-run})"

# The whole bake is one remote root shell. Scalars go as environment in front of
# `sh -s`; the body (REMOTE_SCRIPT) is captured from a single-quoted heredoc, so
# nothing expands locally ($(uname -m), $BATOCERA_REPO, … run on the node). The
# body is fed on stdin, so the same payload serves either auth path below.
REMOTE_CMD="SALT_VERSION=$(printf %q "$SALT_VERSION") \
BATOCERA_REPO=$(printf %q "$BATOCERA_REPO") \
MINION_ID=$(printf %q "$MINION_ID") \
SALT_MASTER=$(printf %q "$SALT_MASTER") \
TEST=$(printf %q "$TEST") \
sh -s"

REMOTE_SCRIPT="$(cat <<'REMOTE'
set -eu

# Map uname -m to the exact published package (mirrors SALT_PACKAGE_URLS):
#   x86_64  -> /x64/misc-salt-<ver>-x86_64.pkg.tar.zst
#   aarch64 -> /arm64/misc-salt-<ver>-any.pkg.tar.zst   (arm ships the 'any' pkg)
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  SALT_PACKAGE_URL="${BATOCERA_REPO}/x64/misc-salt-${SALT_VERSION}-x86_64.pkg.tar.zst" ;;
    aarch64) SALT_PACKAGE_URL="${BATOCERA_REPO}/arm64/misc-salt-${SALT_VERSION}-any.pkg.tar.zst" ;;
    *) echo "!! unsupported arch: $ARCH" >&2; exit 1 ;;
esac
SALT_CALL=/userdata/system/bin/salt-call
PILLAR_FILE=/userdata/system/opt/salt/pillar/batocera.sls
LOG=/userdata/system/logs/bake-node.log
mkdir -p /userdata/system/logs
[ -n "${TEST:-}" ] && TEST_ARG="test=True" || TEST_ARG=""

# Identity -> batocera.conf BEFORE install, so the package's salt-init-minion /
# salt-init-pillar (run by its pacman batoexec hook) pick it up (mirrors
# batocera_pkg._seed_minion_id). Empty values fall back to the package defaults
# (minion-id := system hostname).
if command -v batocera-settings-set >/dev/null 2>&1; then
    [ -n "$MINION_ID" ]   && batocera-settings-set salt.minion-id   "$MINION_ID"
    [ -n "$SALT_MASTER" ] && batocera-settings-set salt.master.host "$SALT_MASTER"
fi

echo "== install-salt =="
echo "   $SALT_PACKAGE_URL"
pacman -U --noconfirm "$SALT_PACKAGE_URL"   # hook seeds the default pillar + minion conf, starts salt_minion

# os-bakery injects the node's rendered pillar between the markers below (a
# quoted heredoc, so the YAML is literal). Empty in the generic script -> keep
# the package's default (inert) pillar. Mirrors batocera_pkg._write_pillar.
NEW_PILLAR="$(cat <<'OSBAKERY_PILLAR_EOF'
OSBAKERY_PILLAR_EOF
)"
if [ -n "$NEW_PILLAR" ]; then
    echo "== write-pillar ($PILLAR_FILE) =="
    mkdir -p "$(dirname "$PILLAR_FILE")"
    printf '%s\n' "$NEW_PILLAR" > "$PILLAR_FILE"
fi

echo "== apply-batocera ${TEST_ARG:+($TEST_ARG)} =="
"$SALT_CALL" --local state.apply batocera $TEST_ARG 2>&1 | tee -a "$LOG"

echo "== apply-global (highstate) ${TEST_ARG:+($TEST_ARG)} =="
"$SALT_CALL" --local state.highstate $TEST_ARG 2>&1 | tee -a "$LOG"

echo "== done: $(hostname) ${TEST_ARG:+(dry run) }baked =="
REMOTE
)"

# Auth: prefer an SSH key from the agent (no password); fall back to the root
# password via sshpass. Probe key auth with BatchMode so it never prompts — if
# a key works, use it; otherwise require sshpass and use the password.
SSH_KEY_OPTS="-o BatchMode=yes -o PreferredAuthentications=publickey -o PasswordAuthentication=no"
# shellcheck disable=SC2086
if ssh $SSH_OPTS $SSH_KEY_OPTS "root@${NODE}" true 2>/dev/null; then
    echo ">> auth: ssh key (agent)"
    # shellcheck disable=SC2086
    printf '%s\n' "$REMOTE_SCRIPT" | ssh $SSH_OPTS $SSH_KEY_OPTS "root@${NODE}" "$REMOTE_CMD"
else
    echo ">> auth: no usable ssh key — falling back to the root password"
    if ! command -v sshpass >/dev/null 2>&1; then
        echo "!! no SSH key worked and sshpass is missing — add a key to your agent (ssh-add) or install sshpass" >&2
        exit 1
    fi
    # shellcheck disable=SC2086
    printf '%s\n' "$REMOTE_SCRIPT" | sshpass -p "$ROOT_PASS" ssh $SSH_OPTS \
        -o PreferredAuthentications=password -o PubkeyAuthentication=no "root@${NODE}" "$REMOTE_CMD"
fi

echo ">> '$NODE' ${TEST:+(dry run) }baked."
