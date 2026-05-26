# The `batocera` formula — applied masterless by `salt-call --local
# state.apply batocera` (at bake in the chroot, and/or on-device). Batocera is
# buildroot with no apt/pkg provider, so this is SELF-CONTAINED: pure file
# states that compile + apply on batocera's bundled salt. Real fleets point
# SALT_STATES_ROOT at their own batocera module instead.
{% set b = pillar.get('batocera', {}) %}
{% set opts = pillar.get('options', {}) %}

batocera_system_dir:
  file.directory:
    - name: /userdata/system
    - makedirs: True

batocera_osbakery_marker:
  file.managed:
    - name: /userdata/system/.osbakery-salt-applied
    - makedirs: True
    - contents: |
        Applied by os-bakery via: salt-call --local state.apply batocera
        hostname: {{ opts.get('hostname', 'batocera') }}
        boot_to_arcade: {{ b.get('boot_to_arcade', False) }}

batocera_conf_boottoarcade:
  file.replace:
    - name: /userdata/system/batocera.conf
    - pattern: '^system\.es\.boottoarcade=.*'
    - repl: 'system.es.boottoarcade={{ 1 if b.get("boot_to_arcade") else 0 }}'
    - append_if_not_found: True
    - create_if_not_exists: True

{% if opts.get('hostname') %}
batocera_conf_hostname:
  file.replace:
    - name: /userdata/system/batocera.conf
    - pattern: '^system\.hostname=.*'
    - repl: 'system.hostname={{ opts["hostname"] }}'
    - append_if_not_found: True
    - create_if_not_exists: True
{% endif %}
