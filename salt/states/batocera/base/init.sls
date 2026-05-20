# Batocera defaults applied to every Batocera image.
# Notes:
#   - Batocera's read-only /boot+/userdata layout means writes go to /userdata.
#   - Configuration lives in /userdata/system/batocera.conf (key=value).

include:
  - base.hardening
  - base.users
  - base.network
  - base.locale

{% set conf = '/userdata/system/batocera.conf' %}
{% set options = pillar.get('options', {}) %}

batocera.base.system_dir:
  file.directory:
    - name: /userdata/system
    - makedirs: True

batocera.base.batocera_conf:
  file.managed:
    - name: {{ conf }}
    - mode: '0644'
    - replace: False
    - contents: |
        # Managed by os-bakery (initial defaults). Subsequent edits via the UI persist.

{% macro setconf(key, value) %}
batocera.base.conf_{{ key | replace('.', '_') }}:
  file.replace:
    - name: {{ conf }}
    - pattern: '^{{ key }}=.*$'
    - repl: '{{ key }}={{ value }}'
    - append_if_not_found: True
{% endmacro %}

{{ setconf('system.timezone', options.get('timezone', 'UTC')) }}
{{ setconf('system.language', options.get('language', 'en_US')) }}
{{ setconf('system.kblayout', options.get('keyboard', 'us')) }}
{{ setconf('wifi.enabled', '1' if options.get('wifi_ssid') else '0') }}
