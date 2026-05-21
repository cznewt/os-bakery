/*
 * Raspberry Pi OS — Bookworm 64-bit — for Raspberry Pi 4.
 *
 * RaspiOS publishes a single arm64 image (lite or desktop) that runs on
 * rpi3/4/5. Variant selects between `lite` (headless / server-like) and
 * `desktop`. Recipes that need per-board firmware tweaks apply them
 * through Salt at build time.
 */

packer { required_plugins {} }

variable "variant" {
  type        = string
  description = "raspios variant: lite | desktop"
  default     = "lite"
}

variable "image_url" {
  type    = string
  default = "https://downloads.raspberrypi.com/raspios_{variant_path}/images/raspios_{variant_path}-latest/raspios_{variant_path}-latest.img.xz"
}

variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  variant_path  = var.variant == "lite" ? "lite_arm64" : "arm64"
  url           = replace(var.image_url, "{variant_path}", local.variant_path)
  archive_path  = "${var.work_root}/raspios-${var.variant}-arm64-latest.img.xz"
  raw_path      = "${var.work_root}/raspios-${var.variant}-arm64-latest.img"
  packed_path   = "${var.cache_root}/raspios/rpi4/raspios-${var.variant}-arm64.img.xz"
  manifest_path = "${var.cache_root}/raspios/rpi4/manifest-${var.variant}.json"
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
      "fetch '${local.url}' '${local.archive_path}' '${var.image_sha256}'",
      "extract '${local.archive_path}' '${local.raw_path}'",
      "pack_xz '${local.raw_path}' '${local.packed_path}'",
      "write_manifest '${local.manifest_path}' '${local.url}' '${local.packed_path}'",
    ]
  }
}
