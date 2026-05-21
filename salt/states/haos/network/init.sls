# Home Assistant OS — first-boot network configuration.
#
# Reference: https://www.home-assistant.io/installation/raspberrypi/#prepare-the-network
#
# HAOS uses NetworkManager. To pre-seed Wi-Fi credentials we drop a
# `my-network` keyfile under `<CONFIG>/network/` — HAOS imports it on first
# boot. Static IPs use the same mechanism.

include:
  - haos.base

{% set haos = pillar.get('haos', {}) %}
{% set options = pillar.get('options', {}) %}
{% set config_mount = haos.get('config_mount') %}
{% set wifi_ssid = options.get('wifi_ssid') %}
{% set wifi_psk = options.get('wifi_psk') %}
{% set wifi_country = options.get('wifi_country', 'DE') %}

{% if config_mount and wifi_ssid %}

haos.network.dir:
  file.directory:
    - name: {{ config_mount }}/network
    - makedirs: True

haos.network.wifi_keyfile:
  file.managed:
    - name: {{ config_mount }}/network/my-network
    - mode: '0600'
    - contents: |
        [connection]
        id={{ wifi_ssid }}
        uuid={{ salt['random.get_str'](16, punctuation=False) }}
        type=wifi

        [wifi]
        mode=infrastructure
        ssid={{ wifi_ssid }}

        [ipv4]
        method=auto

        [ipv6]
        addr-gen-mode=stable-privacy
        method=auto

        [wifi-security]
        auth-alg=open
        key-mgmt=wpa-psk
        psk={{ wifi_psk }}

{% else %}

haos.network.skipped:
  test.show_notification:
    - text: |
        haos.network skipped — no wifi_ssid in options or no config_mount.
{% endif %}
