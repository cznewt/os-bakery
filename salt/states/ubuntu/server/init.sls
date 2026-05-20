# Ubuntu server preset: tuned for headless server workloads.

include:
  - ubuntu.base

ubuntu.server.packages:
  pkg.installed:
    - pkgs:
        - htop
        - tmux
        - vim
        - curl
        - jq
        - ca-certificates
