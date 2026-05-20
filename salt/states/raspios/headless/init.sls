# Pure-headless Raspberry Pi OS — SSH only, no desktop, low memory footprint.

include:
  - raspios.base

raspios.headless.remove_gui:
  pkg.purged:
    - pkgs:
        - lightdm
        - lxde-core
        - lxde-common

raspios.headless.disable_swap_on_sd:
  service.disabled:
    - name: dphys-swapfile
