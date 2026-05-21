# Home Assistant OS — default pillar.
#
# Recipe pillar_overrides + per-build option_values are merged on top of
# these. The orchestrator additionally injects `haos.config_mount` /
# `haos.data_mount` after it loop-mounts the partitions; nothing in the
# `haos.*` states runs without those.

haos:
  # Filled in by builds.orchestrator at run time:
  config_mount: ''
  data_mount: ''

  # HAOS-specific defaults that users typically override.
  default_user: homeassistant
  timezone: UTC
  wifi_country: DE
