# The `batocera` formula — what `salt-call --local state.apply batocera`
# (driven by the pillar's `batocera` top-level key) resolves to. It pulls in
# the batocera baseline. Real fleets point SALT_STATES_ROOT at their own salt
# modules, where this `batocera` formula is their batocera role.
include:
  - batocera.base
