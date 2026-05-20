/*
 * Raspberry Pi OS — Bookworm 32-bit Lite — for Raspberry Pi Zero 2 W.
 *
 * Zero 2 W is armv7 (BCM2837). We use the 32-bit (armhf) lite image.
 */

packer { required_plugins {} }

variable "image_url" {
  type    = string
  default = "https://downloads.raspberrypi.com/raspios_lite_armhf/images/raspios_lite_armhf-latest/raspios_lite_armhf-latest.img.xz"
}
variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  archive_path  = "${var.work_root}/raspios-lite-armhf-latest.img.xz"
  raw_path      = "${var.work_root}/raspios-lite-armhf-latest.img"
  packed_path   = "${var.cache_root}/raspios/rpi-zero2w/raspios-lite-armhf.img.xz"
  manifest_path = "${var.cache_root}/raspios/rpi-zero2w/manifest.json"
}

source "null" "image" { communicator = "none" }

build {
  name    = "raspios-rpi-zero2w"
  sources = ["source.null.image"]

  provisioner "shell-local" {
    inline = [
      "set -euo pipefail",
      "source ${path.root}/../../shared/_lib.sh",
      "mkdir -p ${var.work_root} ${dirname(local.packed_path)}",
      "fetch '${var.image_url}' '${local.archive_path}' '${var.image_sha256}'",
      "extract '${local.archive_path}' '${local.raw_path}'",
      "pack_xz '${local.raw_path}' '${local.packed_path}'",
      "write_manifest '${local.manifest_path}' '${var.image_url}' '${local.packed_path}'",
    ]
  }
}
