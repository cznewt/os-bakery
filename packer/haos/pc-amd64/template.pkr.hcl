/*
 * Home Assistant OS — generic x86_64 (UEFI).
 *
 * Suitable for mini-PCs, NUCs, and arbitrary UEFI hardware. Same caveats
 * as the rpi templates — HAOS is appliance-only; recipes can only inject
 * config files, not run Salt against it.
 */

packer { required_plugins {} }

variable "release"        { type = string; default = "14.2" }
variable "image_url" {
  type    = string
  default = "https://github.com/home-assistant/operating-system/releases/download/{{release}}/haos_generic-x86-64-{{release}}.img.xz"
}
variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  url           = replace(var.image_url, "{{release}}", var.release)
  archive_path  = "${var.work_root}/haos-${var.release}-pc-amd64.img.xz"
  raw_path      = "${var.work_root}/haos-${var.release}-pc-amd64.img"
  packed_path   = "${var.cache_root}/haos/pc-amd64/haos-${var.release}-pc-amd64.img.xz"
  manifest_path = "${var.cache_root}/haos/pc-amd64/manifest.json"
}

source "null" "image" { communicator = "none" }

build {
  name    = "haos-pc-amd64"
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
