# Raspberry Pi OS baseline for any RPi recipe.

include:
  - base.hardening
  - base.users
  - base.network
  - base.locale

{% set options = pillar.get('options', {}) %}

raspios.base.cmdline_console:
  file.replace:
    - name: /boot/firmware/cmdline.txt
    - pattern: 'quiet '
    - repl: ''

raspios.base.enable_ssh:
  file.managed:
    - name: /boot/firmware/ssh
    - contents: ''

{% if options.get('config_overrides') %}
raspios.base.config_overrides:
  file.append:
    - name: /boot/firmware/config.txt
    - text: |
        # os-bakery overrides
        {% for line in options.config_overrides -%}
        {{ line }}
        {% endfor %}
{% endif %}
