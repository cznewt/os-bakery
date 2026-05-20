/*
 * Batocera for Raspberry Pi 4 — base image refresh.
 */

packer { required_plugins {} }

variable "release"        { type = string; default = "41" }
variable "image_url" {
  type    = string
  default = "https://updates.batocera.org/bcm2711/stable/last/batocera-bcm2711-{{release}}-stable.img.gz"
}
variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  url           = replace(var.image_url, "{{release}}", var.release)
  archive_path  = "${var.work_root}/batocera-${var.release}-rpi4.img.gz"
  raw_path      = "${var.work_root}/batocera-${var.release}-rpi4.img"
  packed_path   = "${var.cache_root}/batocera/rpi4/batocera-${var.release}-rpi4.img.xz"
  manifest_path = "${var.cache_root}/batocera/rpi4/manifest.json"
}

source "null" "image" { communicator = "none" }

build {
  name    = "batocera-rpi4"
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
