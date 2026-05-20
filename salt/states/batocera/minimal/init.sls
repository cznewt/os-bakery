# Strip Batocera down to a minimal configuration: no themes prefetched,
# no demo roms, just a working ES launcher.

include:
  - batocera.base

batocera.minimal.cleanup_demo_roms:
  file.absent:
    - name: /userdata/roms/snes/Tetris\ Demo.zip
    - require_in:
        - file: batocera.base.batocera_conf
