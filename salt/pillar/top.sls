# Default pillar top — applied to every minion before recipe-specific overrides.
#
# The orchestrator sets the `os_family` grain to one of {batocera, ubuntu,
# raspios, haos} after mounting + reading the image manifest, so per-OS
# defaults are layered on top of `base.defaults`.

base:
  '*':
    - base.defaults
  'os_family:batocera':
    - match: grain
    - batocera.defaults
  'os_family:ubuntu':
    - match: grain
    - ubuntu.defaults
  'os_family:raspios':
    - match: grain
    - raspios.defaults
  'os_family:haos':
    - match: grain
    - haos.defaults
