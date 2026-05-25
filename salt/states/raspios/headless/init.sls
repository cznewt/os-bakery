# Pure-headless Raspberry Pi OS — SSH only, no desktop, low memory footprint.

include:
  - raspios.base

raspios.headless.remove_gui:
  pkg.purged:
    - pkgs:
        - lightdm
        - lxde-core
        - lxde-common

# Disable dphys-swapfile offline by removing its systemd enable symlink.
# `service.disabled` needs a running systemd; file.absent is chroot-safe and
# is a no-op if the unit was never enabled.
raspios.headless.disable_swap_on_sd:
  file.absent:
    - name: /etc/systemd/system/multi-user.target.wants/dphys-swapfile.service
