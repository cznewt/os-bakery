# Chromium kiosk on auto-login.
# Pillar:
#   options:
#     kiosk_url: https://example.com/dashboard
#     kiosk_user: kiosk

include:
  - raspios.base

{% set options = pillar.get('options', {}) %}
{% set user = options.get('kiosk_user', 'kiosk') %}
{% set url  = options.get('kiosk_url', 'https://example.com') %}

raspios.kiosk.packages:
  pkg.installed:
    - pkgs:
        - chromium-browser
        - unclutter
        - xserver-xorg
        - xinit
        - openbox

raspios.kiosk.user:
  user.present:
    - name: {{ user }}
    - shell: /bin/bash
    - createhome: True
    - groups:
        - audio
        - video
        - tty

raspios.kiosk.autostart:
  file.managed:
    - name: /home/{{ user }}/.xsession
    - mode: '0755'
    - user: {{ user }}
    - contents: |
        #!/bin/sh
        unclutter -idle 0 &
        openbox-session &
        exec chromium-browser --kiosk --noerrdialogs --disable-infobars '{{ url }}'

raspios.kiosk.autologin:
  file.managed:
    - name: /etc/systemd/system/getty@tty1.service.d/override.conf
    - makedirs: True
    - contents: |
        [Service]
        ExecStart=
        ExecStart=-/sbin/agetty --autologin {{ user }} --noclear %I $TERM
