/*
 * Ubuntu — amd64 cloud image for QEMU / KVM.
 *
 * Pulls the standard server cloud image (raw img). Post-processing for native
 * qcow2 / vhdx / OVA is recipe-side; this template just keeps a fresh raw
 * mirror in the cache.
 */

packer { required_plugins {} }

variable "release" { type = string; default = "24.04" }
variable "image_url" {
  type    = string
  default = "https://cloud-images.ubuntu.com/releases/{{release}}/release/ubuntu-{{release}}-server-cloudimg-amd64.img"
}
variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  url           = replace(var.image_url, "{{release}}", var.release)
  raw_path      = "${var.work_root}/ubuntu-${var.release}-vm-qemu-amd64.img"
  packed_path   = "${var.cache_root}/ubuntu/vm-qemu/ubuntu-${var.release}-vm-qemu-amd64.img.xz"
  manifest_path = "${var.cache_root}/ubuntu/vm-qemu/manifest.json"
}

source "null" "image" { communicator = "none" }

build {
  name    = "ubuntu-vm-qemu"
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
