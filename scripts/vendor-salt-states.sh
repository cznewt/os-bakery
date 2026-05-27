#!/usr/bin/env bash
# Vendor the gedu salt file_roots + pillar_roots (from the sibling alcali repo)
# into the build context so the worker images bake them as SALT_STATES_ROOT /
# SALT_PILLAR_ROOT. Re-run this + rebuild the workers whenever the salt content
# changes.
#
#   scripts/vendor-salt-states.sh [path-to-salt-master/docker/files]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"            # os-bakery repo root
SRC="${1:-$ROOT/../alcali/extra/salt-master/docker/files}"
SRC="$(cd "$SRC" && pwd)"
DST="$ROOT/salt/vendor"

[ -d "$SRC/states" ] || { echo "no states/ under $SRC" >&2; exit 1; }
[ -d "$SRC/pillar" ] || { echo "no pillar/ under $SRC" >&2; exit 1; }

rm -rf "$DST/states" "$DST/pillar"
mkdir -p "$DST/states" "$DST/pillar"
cp -a "$SRC/states/." "$DST/states/"
cp -a "$SRC/pillar/." "$DST/pillar/"
touch "$DST/states/.gitkeep" "$DST/pillar/.gitkeep"

echo "vendored from $SRC:"
echo "  states: $(find "$DST/states" -name '*.sls' | wc -l) sls, $(ls -d "$DST"/states/*/ 2>/dev/null | wc -l) formulas"
echo "  pillar: $(find "$DST/pillar" -name '*.sls' | wc -l) sls"
