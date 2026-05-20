/*
 * Batocera x86_64 (PC) — base image refresh.
 */

packer { required_plugins {} }

variable "release"        { type = string; default = "41" }
variable "image_url" {
  type    = string
  default = "https://updates.batocera.org/x86_64/stable/last/batocera-x86_64-{{release}}-stable.img.gz"
}
variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  url           = replace(var.image_url, "{{release}}", var.release)
  archive_path  = "${var.work_root}/batocera-${var.release}-x86_64.img.gz"
  raw_path      = "${var.work_root}/batocera-${var.release}-x86_64.img"
  packed_path   = "${var.cache_root}/batocera/x86_64/batocera-${var.release}-x86_64.img.xz"
  manifest_path = "${var.cache_root}/batocera/x86_64/manifest.json"
}

source "null" "image" { communicator = "none" }

build {
  name    = "batocera-x86_64"
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
