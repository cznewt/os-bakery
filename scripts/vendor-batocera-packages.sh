#!/usr/bin/env bash
# Vendor the batocera pacman packages (salt, alloy) into packages/batocera/<arch>/
# split per architecture, so each worker image only bundles the arch it bakes.
# Source: the batocera-utils packages tree (latest version of each package).
#
#   SRC=~/work/batocera/batocera-utils/packages/misc bash scripts/vendor-batocera-packages.sh
#
# packages/batocera/ is gitignored — these are large prebuilt binaries COPY'd
# into the worker image at build time.
set -euo pipefail

SRC="${SRC:-$HOME/work/batocera/batocera-utils/packages/misc}"
DEST="$(cd "$(dirname "$0")/.." && pwd)/packages/batocera"
PKGS=("misc-salt-3007.8" "misc-alloy-1.11.3")
ARCHES=("aarch64" "x86_64")

rm -rf "$DEST"
for arch in "${ARCHES[@]}"; do
  for pkg in "${PKGS[@]}"; do
    src="$SRC/$pkg"
    [ -d "$src" ] || { echo "MISSING: $src" >&2; exit 1; }
    out="$DEST/$arch/$pkg"
    mkdir -p "$out"
    # Copy the whole package tree but only this arch's binaries (drop the other).
    other=$([ "$arch" = aarch64 ] && echo x86_64 || echo aarch64)
    rsync -a --exclude "userdata/system/bin/$other" "$src/" "$out/"
  done
done
echo "Vendored into $DEST:"
du -sh "$DEST"/* 2>/dev/null
