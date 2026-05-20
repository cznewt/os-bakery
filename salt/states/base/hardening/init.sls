# Baseline hardening applied to every image.
# Conservative defaults: no root SSH, key-based auth only, ufw if available.

{% set sshd = pillar.get('base', {}).get('hardening', {}) %}

base.hardening.sshd_config:
  file.managed:
    - name: /etc/ssh/sshd_config.d/10-os-bakery.conf
    - mode: '0644'
    - contents: |
        # Managed by os-bakery / salt :: base.hardening
        PermitRootLogin {{ sshd.get('permit_root_login', 'no') }}
        PasswordAuthentication {{ sshd.get('password_authentication', 'no') }}
        ChallengeResponseAuthentication no
        UsePAM yes
        X11Forwarding no
        ClientAliveInterval {{ sshd.get('client_alive_interval', 300) }}
        ClientAliveCountMax {{ sshd.get('client_alive_count_max', 2) }}

{% if salt['pkg.version']('ufw') %}
base.hardening.ufw_enabled:
  service.enabled:
    - name: ufw
{% endif %}
