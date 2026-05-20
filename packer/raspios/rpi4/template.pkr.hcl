/*
 * Raspberry Pi OS — Bookworm 64-bit Lite — for Raspberry Pi 4.
 *
 * RPi4 uses the same arm64 lite image as RPi5; the difference is mostly
 * boot firmware. Recipes that target rpi4 vs rpi5 can apply different
 * config.txt fragments through Salt.
 */

packer { required_plugins {} }

variable "image_url" {
  type    = string
  default = "https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-latest/raspios_lite_arm64-latest.img.xz"
}
variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  archive_path  = "${var.work_root}/raspios-lite-arm64-latest.img.xz"
  raw_path      = "${var.work_root}/raspios-lite-arm64-latest.img"
  packed_path   = "${var.cache_root}/raspios/rpi4/raspios-lite-arm64.img.xz"
  manifest_path = "${var.cache_root}/raspios/rpi4/manifest.json"
}

source "null" "image" { communicator = "none" }

build {
  name    = "raspios-rpi4"
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
