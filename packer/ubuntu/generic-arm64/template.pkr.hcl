/*
 * Ubuntu — arm64 cloud image (generic, non-Pi).
 *
 * For Ampere servers, cloud VMs, and arbitrary ARM64 SBCs that boot via UEFI.
 * Server variant only; desktop arm64 cloud image is not officially published.
 */

packer { required_plugins {} }

variable "release" { type = string; default = "24.04" }
variable "image_url" {
  type    = string
  default = "https://cloud-images.ubuntu.com/releases/{{release}}/release/ubuntu-{{release}}-server-cloudimg-arm64.img"
}
variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  url           = replace(var.image_url, "{{release}}", var.release)
  raw_path      = "${var.work_root}/ubuntu-${var.release}-generic-arm64.img"
  packed_path   = "${var.cache_root}/ubuntu/generic-arm64/ubuntu-${var.release}-generic-arm64.img.xz"
  manifest_path = "${var.cache_root}/ubuntu/generic-arm64/manifest.json"
}

source "null" "image" { communicator = "none" }

build {
  name    = "ubuntu-generic-arm64"
  sources = ["source.null.image"]

  provisioner "shell-local" {
    inline = [
      "set -euo pipefail",
      "source ${path.root}/../../shared/_lib.sh",
      "mkdir -p ${var.work_root} ${dirname(local.packed_path)}",
      "fetch '${local.url}' '${local.raw_path}' '${var.image_sha256}'",
      "pack_xz '${local.raw_path}' '${local.packed_path}'",
      "write_manifest '${local.manifest_path}' '${local.url}' '${local.packed_path}'",
    ]
  }
}
