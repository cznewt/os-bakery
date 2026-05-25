#!/usr/bin/env bash
# One-shot prod deploy for os-bakery → a single Docker host.
#
# Prereqs on THIS machine: ssh access to the host, and a filled-in .env next to
# compose.prod.yaml (run from the repo root).
#
# Usage:
#   HOST=root@10.50.20.226 \
#   GHCR_PULL_USER=cznewt GHCR_PULL_TOKEN=ghp_xxx \
#   bash scripts/deploy-prod.sh
#
# If the GHCR packages are PUBLIC, omit GHCR_PULL_USER/TOKEN — no login needed.
# If PRIVATE, the token MUST have the read:packages scope (a project,repo token
# will NOT pull and the compose pull will fail with "denied").
set -euo pipefail

HOST="${HOST:-root@10.50.20.226}"
REMOTE_DIR="${REMOTE_DIR:-/opt/os-bakery}"
GHCR_PULL_USER="${GHCR_PULL_USER:-}"
GHCR_PULL_TOKEN="${GHCR_PULL_TOKEN:-}"

cd "$(dirname "$0")/.."

[ -f compose.prod.yaml ] || { echo "FATAL: compose.prod.yaml not found" >&2; exit 1; }
[ -f .env ]              || { echo "FATAL: .env not found (cp .env.prod.example .env && edit)" >&2; exit 1; }

echo "==> [1/5] checking host reachability ($HOST)"
ssh "$HOST" 'echo "    connected to $(hostname)"'

echo "==> [2/5] ensuring Docker + compose plugin are installed"
ssh "$HOST" 'command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 \
  || { echo "    installing Docker via get.docker.com…"; curl -fsSL https://get.docker.com | sh; }
  docker --version; docker compose version'

echo "==> [3/5] copying compose.prod.yaml + .env to $HOST:$REMOTE_DIR"
ssh "$HOST" "mkdir -p '$REMOTE_DIR'"
scp compose.prod.yaml "$HOST:$REMOTE_DIR/compose.prod.yaml"
scp .env              "$HOST:$REMOTE_DIR/.env"
ssh "$HOST" "chmod 600 '$REMOTE_DIR/.env'"

if [ -n "$GHCR_PULL_TOKEN" ]; then
  echo "==> [4/5] docker login ghcr.io as ${GHCR_PULL_USER:-<user>}"
  ssh "$HOST" "echo '$GHCR_PULL_TOKEN' | docker login ghcr.io -u '$GHCR_PULL_USER' --password-stdin"
else
  echo "==> [4/5] no GHCR token given — assuming PUBLIC packages (skipping login)"
fi

echo "==> [5/5] pull + up"
ssh "$HOST" "cd '$REMOTE_DIR' && docker compose -f compose.prod.yaml pull && docker compose -f compose.prod.yaml up -d"

echo
echo "==> status"
ssh "$HOST" "cd '$REMOTE_DIR' && docker compose -f compose.prod.yaml ps"
echo
echo "==> web health (expect HTTP 200/302 once migrations finish)"
ssh "$HOST" "sleep 5; curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://localhost:8000/ || true"
echo
echo "Done. App: http://${HOST#*@}:8000   MinIO console: tunnel to 127.0.0.1:9001 on the host."
