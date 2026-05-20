# Universal defaults — overridden by recipe pillar_overrides and option_values.

base:
  timezone: UTC
  locale: en_US.UTF-8
  hardening:
    permit_root_login: 'no'
    password_authentication: 'no'
    client_alive_interval: 300
    client_alive_count_max: 2
