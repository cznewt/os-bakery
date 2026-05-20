/*
 * Ubuntu Server LTS — arm64 — preinstalled ARM image.
 *
 * Ubuntu publishes preinstalled images for RPi and generic UEFI ARM; we use
 * the generic preinstalled-server ARM image, which the recipe can then specialise
 * for any arm64 board.
 */

packer { required_plugins {} }

variable "release"        { type = string; default = "24.04" }
variable "image_url" {
  type    = string
  default = "https://cdimage.ubuntu.com/releases/{{release}}/release/ubuntu-{{release}}-preinstalled-server-arm64+raspi.img.xz"
}
variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  url           = replace(var.image_url, "{{release}}", var.release)
  archive_path  = "${var.work_root}/ubuntu-${var.release}-arm64.img.xz"
  raw_path      = "${var.work_root}/ubuntu-${var.release}-arm64.img"
  packed_path   = "${var.cache_root}/ubuntu/arm64/ubuntu-${var.release}-arm64.img.xz"
  manifest_path = "${var.cache_root}/ubuntu/arm64/manifest.json"
}

source "null" "image" { communicator = "none" }

build {
  name    = "ubuntu-arm64"
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
