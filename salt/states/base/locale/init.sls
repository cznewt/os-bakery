# Locale + timezone + keyboard layout.

{% set options = pillar.get('options', {}) %}
{% set base = pillar.get('base', {}) %}
{% set tz = options.get('timezone', base.get('timezone', 'UTC')) %}
{% set locale = options.get('locale', base.get('locale', 'en_US.UTF-8')) %}

# Set the timezone with plain files instead of `timezone.system`: that module
# shells out to `timedatectl`, which needs a running systemd (PID 1) and fails
# inside a chroot bake. Writing /etc/timezone + the /etc/localtime symlink is
# exactly what timedatectl does, and works offline.
base.locale.timezone_etc:
  file.managed:
    - name: /etc/timezone
    - contents: {{ tz }}

base.locale.timezone_localtime:
  file.symlink:
    - name: /etc/localtime
    - target: /usr/share/zoneinfo/{{ tz }}
    - force: True
    - require:
        - file: base.locale.timezone_etc

base.locale.generated:
  locale.present:
    - name: {{ locale }}

base.locale.default:
  locale.system:
    - name: {{ locale }}
    - require:
        - locale: base.locale.generated
