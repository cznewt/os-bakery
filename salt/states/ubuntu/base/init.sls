# Ubuntu baseline.

include:
  - base.hardening
  - base.users
  - base.network
  - base.locale

ubuntu.base.unattended_upgrades:
  pkg.installed:
    - name: unattended-upgrades

ubuntu.base.enable_auto_updates:
  file.managed:
    - name: /etc/apt/apt.conf.d/20auto-upgrades
    - contents: |
        APT::Periodic::Update-Package-Lists "1";
        APT::Periodic::Unattended-Upgrade "1";
