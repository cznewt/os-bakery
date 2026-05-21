/*
 * Ubuntu — amd64 for generic x86_64 PCs.
 *
 * (Renamed from the legacy `amd64` directory; HardwareTarget slug is
 * `pc-amd64`.) Variant flips between the server cloud image (raw .img) and
 * the desktop live-installer ISO. Both end up as `.img.xz` in the cache;
 * the orchestrator's mount step knows how to handle each format.
 */

packer { required_plugins {} }

variable "release" { type = string; default = "24.04" }
variable "variant" {
  type        = string
  description = "Ubuntu variant: server | desktop"
  default     = "server"
}

variable "server_image_url" {
  type    = string
  default = "https://cloud-images.ubuntu.com/releases/{{release}}/release/ubuntu-{{release}}-server-cloudimg-amd64.img"
}
variable "desktop_image_url" {
  type    = string
  default = "https://releases.ubuntu.com/{{release}}/ubuntu-{{release}}.1-desktop-amd64.iso"
}

variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  raw_url       = var.variant == "desktop" ? var.desktop_image_url : var.server_image_url
  url           = replace(local.raw_url, "{{release}}", var.release)
  ext           = var.variant == "desktop" ? "iso" : "img"
  src_path      = "${var.work_root}/ubuntu-${var.release}-${var.variant}-pc-amd64.${local.ext}"
  packed_path   = "${var.cache_root}/ubuntu/pc-amd64/ubuntu-${var.release}-${var.variant}-pc-amd64.${local.ext}.xz"
  manifest_path = "${var.cache_root}/ubuntu/pc-amd64/manifest-${var.variant}.json"
}

source "null" "image" { communicator = "none" }

build {
  name    = "ubuntu-pc-amd64"
  sources = ["source.null.image"]

  provisioner "shell-local" {
    inline = [
      "set -euo pipefail",
      "source ${path.root}/../../shared/_lib.sh",
      "mkdir -p ${var.work_root} ${dirname(local.packed_path)}",
      "fetch '${local.url}' '${local.src_path}' '${var.image_sha256}'",
      "pack_xz '${local.src_path}' '${local.packed_path}'",
      "write_manifest '${local.manifest_path}' '${local.url}' '${local.packed_path}'",
    ]
  }
}
