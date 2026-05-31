#!/usr/bin/env bash
#
# bake-node.sh — "bake" a LIVE Batocera node over SSH.
#
# Does to a running node what os-bakery does to an image at build time
# (builds/provisioners/batocera_pkg.py), but reached over SSH instead of a
# chroot:
#
#     install the misc-salt package   (pacman -U <salt pkg url>)
#       -> the package's batoexec hook populates the pillar + minion config
#          and starts salt_minion
#       -> salt-call --local state.apply batocera   (configures the repos)
#       -> salt-call --local state.highstate        (global: the pillar states)
#
# Usage:
#     ./bake-node.sh <node-ip-or-hostname>
#
# Connects as root with Batocera's default password ("linux"); requires sshpass.
# Optional overrides via env:
#     MINION_ID=arcade-1 SALT_MASTER=salt.lan ./bake-node.sh 10.0.0.5
#     SALT_VERSION=3007.14-6 BATOCERA_REPO=https://utils.batocera.gameedu.eu
#     BATOCERA_ROOT_PASS=linux
#
set -euo pipefail

NODE="${1:-}"
if [ -z "$NODE" ]; then
    echo "usage: $0 <node-ip-or-hostname>" >&2
    exit 1
fi

# Defaults mirror os-bakery's SALT_PACKAGE_URLS (compose.prod.yaml).
SALT_VERSION="${SALT_VERSION:-3007.14-6}"
BATOCERA_REPO="${BATOCERA_REPO:-https://utils.batocera.gameedu.eu}"
MINION_ID="${MINION_ID:-}"               # empty -> the node's own hostname
SALT_MASTER="${SALT_MASTER:-}"           # empty -> leave the package default
ROOT_PASS="${BATOCERA_ROOT_PASS:-linux}" # Batocera default root password

if ! command -v sshpass >/dev/null 2>&1; then
    echo "!! sshpass is required (e.g. 'apt install sshpass' / 'pacman -S sshpass')" >&2
    exit 1
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"

echo ">> baking node '$NODE'  (salt $SALT_VERSION, repo $BATOCERA_REPO)"

# Everything runs in one remote root shell. Config is passed as environment in
# front of `sh -s`; the heredoc is single-quoted so only the REMOTE shell
# expands it ($(uname -m), $BATOCERA_REPO, … stay untouched locally).
# shellcheck disable=SC2086
sshpass -p "$ROOT_PASS" ssh $SSH_OPTS "root@${NODE}" \
    "SALT_VERSION=$(printf %q "$SALT_VERSION") \
     BATOCERA_REPO=$(printf %q "$BATOCERA_REPO") \
     MINION_ID=$(printf %q "$MINION_ID") \
     SALT_MASTER=$(printf %q "$SALT_MASTER") \
     sh -s" <<'REMOTE'
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
LOG=/userdata/system/logs/bake-node.log
mkdir -p /userdata/system/logs

# Identity → batocera.conf BEFORE install, so the package's salt-init-minion /
# salt-init-pillar (run by its pacman batoexec hook) pick it up (mirrors
# batocera_pkg._seed_minion_id). Empty values fall back to the package defaults
# (minion-id := system hostname).
if command -v batocera-settings-set >/dev/null 2>&1; then
    [ -n "$MINION_ID" ]   && batocera-settings-set salt.minion-id   "$MINION_ID"
    [ -n "$SALT_MASTER" ] && batocera-settings-set salt.master.host "$SALT_MASTER"
fi

echo "== install-salt =="
echo "   $SALT_PACKAGE_URL"
pacman -U --noconfirm "$SALT_PACKAGE_URL"   # hook populates pillar + minion conf, starts salt_minion

echo "== apply-batocera =="
"$SALT_CALL" --local state.apply batocera 2>&1 | tee -a "$LOG"

echo "== apply-global (highstate) =="
"$SALT_CALL" --local state.highstate 2>&1 | tee -a "$LOG"

echo "== done: $(hostname) baked =="
REMOTE

echo ">> '$NODE' baked."
