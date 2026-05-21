# Home Assistant OS — base bake-time customization.
#
# HAOS is an immutable appliance OS — there is no apt, no Python, and you
# cannot run salt-call on the *running* device. Everything in this tree
# therefore writes files into mounted HAOS partitions at *bake time*:
#
#   - CONFIG partition  → mounted at `pillar.haos.config_mount` (e.g.
#     /mnt/haos-config). FAT32, labelled `hassos-data` on a fresh image.
#   - DATA  partition   → mounted at `pillar.haos.data_mount`. ext4,
#     contains `/supervisor/homeassistant/configuration.yaml` and friends.
#
# Recipes that don't supply mount points should NOT include this formula —
# the orchestrator skips Salt entirely for HAOS recipes unless explicit
# mount points are present in the pillar.

{% set haos = pillar.get('haos', {}) %}
{% set options = pillar.get('options', {}) %}
{% set config_mount = haos.get('config_mount') %}

{% if not config_mount %}
haos.base.skipped_no_mount:
  test.show_notification:
    - text: |
        Skipping haos.base — pillar.haos.config_mount is not set. HAOS
        customizations only run when the orchestrator mounts the image
        and exports the partition paths into the pillar.
{% else %}

haos.base.config_mount_exists:
  file.directory:
    - name: {{ config_mount }}
    - makedirs: True

# A `.HA_VERSION`-style marker so we can tell hand-edited config partitions
# apart from os-bakery-baked ones. Harmless if HA ignores it.
haos.base.bakery_marker:
  file.managed:
    - name: {{ config_mount }}/.os-bakery
    - contents: |
        # Baked by os-bakery {{ salt['cmd.run']('date -u +%Y-%m-%dT%H:%M:%SZ') }}
        recipe: {{ options.get('recipe', 'unknown') }}
        hostname: {{ options.get('hostname', '') }}

{% endif %}
