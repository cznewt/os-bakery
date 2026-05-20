# Single-node k3s install for edge / arm SBC workloads.
# Pillar:
#   options:
#     k3s_disable: [traefik, servicelb]
#     k3s_token: <node token>

include:
  - ubuntu.server

{% set options = pillar.get('options', {}) %}

ubuntu.k3s.install:
  cmd.run:
    - name: |
        curl -sfL https://get.k3s.io | \
          INSTALL_K3S_VERSION='{{ options.get('k3s_version', 'stable') }}' \
          K3S_TOKEN='{{ options.get('k3s_token', '') }}' \
          sh -s - server \
            {% for d in options.get('k3s_disable', []) -%}
            --disable {{ d }} \
            {% endfor %}
            --write-kubeconfig-mode 644
    - unless: test -f /usr/local/bin/k3s
