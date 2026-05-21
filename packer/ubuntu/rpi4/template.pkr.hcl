/*
 * Ubuntu — arm64 preinstalled for Raspberry Pi 4.
 *
 * Canonical publishes `preinstalled-{server,desktop}-arm64+raspi.img.xz`
 * images that run on rpi4 / rpi5. Variant flips between them.
 */

packer { required_plugins {} }

variable "release" { type = string; default = "24.04" }
variable "variant" {
  type        = string
  description = "Ubuntu variant: server | desktop"
  default     = "server"
}

variable "image_url" {
  type    = string
  default = "https://cdimage.ubuntu.com/releases/{{release}}/release/ubuntu-{{release}}-preinstalled-{{variant}}-arm64+raspi.img.xz"
}

variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  url           = replace(replace(var.image_url, "{{release}}", var.release), "{{variant}}", var.variant)
  archive_path  = "${var.work_root}/ubuntu-${var.release}-${var.variant}-rpi4.img.xz"
  raw_path      = "${var.work_root}/ubuntu-${var.release}-${var.variant}-rpi4.img"
  packed_path   = "${var.cache_root}/ubuntu/rpi4/ubuntu-${var.release}-${var.variant}-rpi4.img.xz"
  manifest_path = "${var.cache_root}/ubuntu/rpi4/manifest-${var.variant}.json"
}

source "null" "image" { communicator = "none" }

build {
  name    = "ubuntu-rpi4"
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
