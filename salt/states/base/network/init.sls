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

base.network.wlan0_unit_enabled:
  service.enabled:
    - name: wpa_supplicant@wlan0
{% endif %}
