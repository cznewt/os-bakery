# Raspberry Pi OS with docker + portainer preinstalled.

include:
  - raspios.base

raspios.docker.repo:
  pkgrepo.managed:
    - humanname: Docker CE
    - name: deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable
    - file: /etc/apt/sources.list.d/docker.list
    - key_url: https://download.docker.com/linux/debian/gpg
    - aptkey: False

raspios.docker.packages:
  pkg.installed:
    - pkgs:
        - docker-ce
        - docker-ce-cli
        - containerd.io
        - docker-buildx-plugin
        - docker-compose-plugin

raspios.docker.service:
  service.enabled:
    - name: docker

raspios.docker.portainer:
  cmd.run:
    - name: |
        docker volume create portainer_data
        docker run -d \
          -p 9443:9443 \
          --restart=unless-stopped \
          --name portainer \
          -v /var/run/docker.sock:/var/run/docker.sock \
          -v portainer_data:/data \
          portainer/portainer-ce:latest
    - unless: docker ps --format '{{ "{{ .Names }}" }}' | grep -qx portainer
    - require:
        - service: raspios.docker.service
