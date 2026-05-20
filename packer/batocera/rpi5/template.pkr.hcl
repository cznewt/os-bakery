/*
 * Batocera for Raspberry Pi 5 — base image refresh.
 *
 * Downloads the official Batocera RPi5 release, optionally bakes a couple of
 * shared "core" Salt states into it (kernel modules, default config), then
 * drops the result into the os-bakery cache and writes a manifest the Django
 * app can ingest.
 */

packer {
  required_plugins {}
}

variable "release" {
  type        = string
  description = "Batocera release version (e.g. \"41\")."
  default     = "41"
}

variable "image_url" {
  type    = string
  default = "https://updates.batocera.org/bcm2712/stable/last/batocera-bcm2712-{{release}}-stable.img.gz"
}

variable "image_sha256" {
  type    = string
  default = ""
}

variable "cache_root" {
  type    = string
  default = "${env("HOME")}/.cache/os-bakery"
}

variable "work_root" {
  type    = string
  default = "/tmp/os-bakery-packer"
}

locals {
  url            = replace(var.image_url, "{{release}}", var.release)
  archive_path   = "${var.work_root}/batocera-${var.release}-rpi5.img.gz"
  raw_path       = "${var.work_root}/batocera-${var.release}-rpi5.img"
  packed_path    = "${var.cache_root}/batocera/rpi5/batocera-${var.release}-rpi5.img.xz"
  manifest_path  = "${var.cache_root}/batocera/rpi5/manifest.json"
}

source "null" "image" {
  communicator = "none"
}

build {
  name    = "batocera-rpi5"
  sources = ["source.null.image"]

  provisioner "shell-local" {
    inline = [
      "set -euo pipefail",
      "source ${path.root}/../../shared/_lib.sh",
      "mkdir -p ${var.work_root} ${dirname(local.packed_path)}",
      "fetch '${local.url}' '${local.archive_path}' '${var.image_sha256}'",
      "extract '${local.archive_path}' '${local.raw_path}'",
      // Hook point: insert mount + salt-call here when a real environment is available.
      "pack_xz '${local.raw_path}' '${local.packed_path}'",
      "write_manifest '${local.manifest_path}' '${local.url}' '${local.packed_path}'",
    ]
  }
}
