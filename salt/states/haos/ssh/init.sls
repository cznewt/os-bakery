# Home Assistant OS — pre-seed authorized SSH keys for the SSH add-on.
#
# The SSH and Web Terminal add-on reads `<CONFIG>/.ssh/authorized_keys` on
# first start. Pre-seeding it lets the user log into the new HA host
# without first touching the UI to enable + configure SSH.

include:
  - haos.base

{% set haos = pillar.get('haos', {}) %}
{% set options = pillar.get('options', {}) %}
{% set config_mount = haos.get('config_mount') %}
{% set keys = options.get('ssh_authorized_keys', []) %}

{% if config_mount and keys %}

haos.ssh.dir:
  file.directory:
    - name: {{ config_mount }}/.ssh
    - mode: '0700'
    - makedirs: True

haos.ssh.authorized_keys:
  file.managed:
    - name: {{ config_mount }}/.ssh/authorized_keys
    - mode: '0600'
    - contents: |
        # Managed by os-bakery
        {%- for key in keys %}
        {{ key }}
        {%- endfor %}

{% else %}

haos.ssh.skipped:
  test.show_notification:
    - text: |
        haos.ssh skipped — no ssh_authorized_keys in options or no config_mount.
{% endif %}
