/*
 * Batocera for Raspberry Pi 3 — base image refresh.
 *
 * Batocera publishes per-SoC builds; rpi3 maps to the BCM2710 line. Note:
 * upstream has periodically dropped active rpi3 development — verify the URL
 * still serves a current image before relying on it.
 */

packer { required_plugins {} }

variable "release" {
  type        = string
  description = "Batocera release version (e.g. \"41\")."
  default     = "41"
}

variable "image_url" {
  type    = string
  default = "https://updates.batocera.org/bcm2710/stable/last/batocera-bcm2710-{{release}}-stable.img.gz"
}

variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  url           = replace(var.image_url, "{{release}}", var.release)
  archive_path  = "${var.work_root}/batocera-${var.release}-rpi3.img.gz"
  raw_path      = "${var.work_root}/batocera-${var.release}-rpi3.img"
  packed_path   = "${var.cache_root}/batocera/rpi3/batocera-${var.release}-rpi3.img.xz"
  manifest_path = "${var.cache_root}/batocera/rpi3/manifest.json"
}

source "null" "image" { communicator = "none" }

build {
  name    = "batocera-rpi3"
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
