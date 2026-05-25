# Network configuration baked into the image.
# Pillar contract:
#   options:
#     wifi_ssid: my-ssid
#     wifi_password: hunter2          # rendered via secrets at build time
#     wifi_country: CZ
#     ethernet_dhcp: true              # default

{% set options = pillar.get('options', {}) %}
{% set ssid = options.get('wifi_ssid') %}
{% set country = options.get('wifi_country', 'US') %}

{% if ssid %}
base.network.wpa_supplicant:
  file.managed:
    - name: /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
    - mode: '0600'
    - contents: |
        country={{ country }}
        ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
        update_config=1
        network={
          ssid="{{ ssid }}"
          psk="{{ options.get('wifi_password', '') }}"
          key_mgmt=WPA-PSK
        }

# Enable wpa_supplicant@wlan0 by creating the systemd `wants` symlink directly.
# `service.enabled` calls `systemctl enable`, which can't enumerate a
# template-instance unit without a running systemd — it errors in a chroot.
# This symlink is exactly what `systemctl enable` would create, applied offline.
base.network.wlan0_unit_enabled:
  file.symlink:
    - name: /etc/systemd/system/multi-user.target.wants/wpa_supplicant@wlan0.service
    - target: /lib/systemd/system/wpa_supplicant@.service
    - makedirs: True
{% endif %}
