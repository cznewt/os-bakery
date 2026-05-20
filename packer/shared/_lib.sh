#!/usr/bin/env bash
# Helpers sourced by every template's shell-local provisioner.
# All paths are expected to be absolute by the time we get here.
set -euo pipefail

log() {
    printf '[os-bakery/packer] %s\n' "$*" >&2
}

# Download an image from $1 to $2, verifying sha256 if $3 is set.
fetch() {
    local url="$1" out="$2" want_sha="${3:-}"
    if [[ -f "$out" ]] && [[ -n "$want_sha" ]]; then
        local have_sha
        have_sha=$(sha256sum "$out" | awk '{print $1}')
        if [[ "$have_sha" == "$want_sha" ]]; then
            log "cache hit for $out"
            return 0
        fi
    fi
    log "fetching $url -> $out"
    mkdir -p "$(dirname "$out")"
    curl -fL --retry 3 --retry-delay 2 -o "$out" "$url"
    if [[ -n "$want_sha" ]]; then
        echo "$want_sha  $out" | sha256sum -c -
    fi
}

# Extract a downloaded image archive into $2.
extract() {
    local archive="$1" out="$2"
    log "extracting $archive -> $out"
    mkdir -p "$(dirname "$out")"
    case "$archive" in
        *.img.xz) xz -dkc "$archive" > "$out" ;;
        *.img.gz) gzip -dkc "$archive" > "$out" ;;
        *.zip)    unzip -p "$archive" > "$out" ;;
        *.img)    cp "$archive" "$out" ;;
        *) log "unknown archive format: $archive"; exit 2 ;;
    esac
}

# Repackage a raw .img back into .img.xz for distribution.
pack_xz() {
    local raw="$1" out="$2"
    log "packing $raw -> $out"
    xz -T0 -z -c "$raw" > "$out"
}

# Write a manifest.json that the Django app can ingest.
write_manifest() {
    local target="$1"
    local source_url="$2"
    local image_path="$3"
    local sha256
    sha256=$(sha256sum "$image_path" | awk '{print $1}')
    local size
    size=$(stat -c '%s' "$image_path")
    cat > "$target" <<JSON
{
  "source_url": "$source_url",
  "local_path": "$image_path",
  "size_bytes": $size,
  "sha256": "$sha256",
  "built_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSON
    log "wrote manifest at $target"
}
