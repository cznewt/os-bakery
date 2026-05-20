# Default + admin user provisioning.
# Pillar contract:
#   options:
#     admin_username: bakery
#     admin_ssh_keys:
#       - ssh-ed25519 AAAA...
#     hostname: my-pi

{% set options = pillar.get('options', {}) %}
{% set username = options.get('admin_username', 'bakery') %}
{% set ssh_keys = options.get('admin_ssh_keys', []) %}

base.users.admin:
  user.present:
    - name: {{ username }}
    - shell: /bin/bash
    - createhome: True
    - groups:
        - sudo

base.users.admin_sudoers:
  file.managed:
    - name: /etc/sudoers.d/10-{{ username }}
    - mode: '0440'
    - contents: |
        {{ username }} ALL=(ALL) NOPASSWD: ALL

{% for key in ssh_keys %}
base.users.admin_ssh_key_{{ loop.index }}:
  ssh_auth.present:
    - user: {{ username }}
    - name: {{ key }}
{% endfor %}

{% if options.get('hostname') %}
base.users.hostname:
  cmd.run:
    - name: 'echo {{ options.hostname }} > /etc/hostname'
    - unless: 'grep -qx {{ options.hostname }} /etc/hostname'
{% endif %}
