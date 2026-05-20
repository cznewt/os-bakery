# Family-friendly Batocera: parental controls on, modern consoles only,
# theme set to something tidy.

include:
  - batocera.base

{% set conf = '/userdata/system/batocera.conf' %}

batocera.family.parental_controls:
  file.replace:
    - name: {{ conf }}
    - pattern: '^kidmode\..*$'
    - repl: 'kidmode.enabled=1'
    - append_if_not_found: True

batocera.family.theme:
  file.replace:
    - name: {{ conf }}
    - pattern: '^emulationstation.theme.set=.*$'
    - repl: 'emulationstation.theme.set=es-theme-carbon'
    - append_if_not_found: True
