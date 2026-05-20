// Shared variables for every os-bakery Packer template.
// Override per-environment via `-var-file=` (see dev.pkrvars.hcl.example).

variable "cache_root" {
  type        = string
  description = "Directory where refreshed base images are dropped (matches catalog.UpstreamImage.local_path)."
  default     = "${env("HOME")}/.cache/os-bakery"
}

variable "work_root" {
  type        = string
  description = "Scratch directory used while downloading/repacking."
  default     = "/tmp/os-bakery-packer"
}

variable "publish_manifest" {
  type        = bool
  description = "Whether to write a manifest.json next to the produced image."
  default     = true
}

variable "core_salt_states" {
  type        = list(string)
  description = "Optional Salt states to apply during the base-image bake (hardening, base user, etc.)."
  default     = []
}

variable "core_salt_pillar" {
  type        = map(any)
  description = "Pillar fed to core_salt_states."
  default     = {}
}
