/*
 * Home Assistant OS — Raspberry Pi 4.
 *
 * HAOS is an immutable appliance OS — Packer here just mirrors the upstream
 * `.img.xz` into the cache. The orchestrator does NOT run salt-call against
 * HAOS images; per-build customizations are limited to file injection on the
 * config / data partitions before flashing.
 */

packer { required_plugins {} }

variable "release"        { type = string; default = "14.2" }
variable "image_url" {
  type    = string
  default = "https://github.com/home-assistant/operating-system/releases/download/{{release}}/haos_rpi4-64-{{release}}.img.xz"
}
variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  url           = replace(var.image_url, "{{release}}", var.release)
  archive_path  = "${var.work_root}/haos-${var.release}-rpi4.img.xz"
  raw_path      = "${var.work_root}/haos-${var.release}-rpi4.img"
  packed_path   = "${var.cache_root}/haos/rpi4/haos-${var.release}-rpi4.img.xz"
  manifest_path = "${var.cache_root}/haos/rpi4/manifest.json"
}

source "null" "image" { communicator = "none" }

build {
  name    = "haos-rpi4"
  sources = ["source.null.image"]

  provisioner "shell-local" {
    inline = [
      "set -euo pipefail",
      "source ${path.root}/../../shared/_lib.sh",
      "mkdir -p ${var.work_root} ${dirname(local.packed_path)}",
      "fetch '${local.url}' '${local.archive_path}' '${var.image_sha256}'",
      "extract '${local.archive_path}' '${local.raw_path}'",
      "pack_xz '${local.raw_path}' '${local.packed_path}'",
      "write_manifest '${local.manifest_path}' '${local.url}' '${local.packed_path}'",
    ]
  }
}
