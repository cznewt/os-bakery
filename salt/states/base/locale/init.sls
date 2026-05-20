# Locale + timezone + keyboard layout.

{% set options = pillar.get('options', {}) %}
{% set base = pillar.get('base', {}) %}
{% set tz = options.get('timezone', base.get('timezone', 'UTC')) %}
{% set locale = options.get('locale', base.get('locale', 'en_US.UTF-8')) %}

base.locale.timezone:
  timezone.system:
    - name: {{ tz }}

base.locale.generated:
  locale.present:
    - name: {{ locale }}

base.locale.default:
  locale.system:
    - name: {{ locale }}
    - require:
        - locale: base.locale.generated
