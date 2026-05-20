/*
 * Ubuntu Server LTS — amd64 — cloud image (qcow2 → raw → img.xz).
 */

packer { required_plugins {} }

variable "release"        { type = string; default = "24.04" }
variable "image_url" {
  type    = string
  default = "https://cloud-images.ubuntu.com/releases/{{release}}/release/ubuntu-{{release}}-server-cloudimg-amd64.img"
}
variable "image_sha256"   { type = string; default = "" }
variable "cache_root"     { type = string; default = "${env("HOME")}/.cache/os-bakery" }
variable "work_root"      { type = string; default = "/tmp/os-bakery-packer" }

locals {
  url           = replace(var.image_url, "{{release}}", var.release)
  qcow_path     = "${var.work_root}/ubuntu-${var.release}-amd64.qcow2"
  raw_path      = "${var.work_root}/ubuntu-${var.release}-amd64.img"
  packed_path   = "${var.cache_root}/ubuntu/amd64/ubuntu-${var.release}-amd64.img.xz"
  manifest_path = "${var.cache_root}/ubuntu/amd64/manifest.json"
}

source "null" "image" { communicator = "none" }

build {
  name    = "ubuntu-amd64"
  sources = ["source.null.image"]

  provisioner "shell-local" {
    inline = [
      "set -euo pipefail",
      "source ${path.root}/../../shared/_lib.sh",
      "mkdir -p ${var.work_root} ${dirname(local.packed_path)}",
      "fetch '${local.url}' '${local.qcow_path}' '${var.image_sha256}'",
      "qemu-img convert -O raw '${local.qcow_path}' '${local.raw_path}'",
      "pack_xz '${local.raw_path}' '${local.packed_path}'",
      "write_manifest '${local.manifest_path}' '${local.url}' '${local.packed_path}'",
    ]
  }
}
