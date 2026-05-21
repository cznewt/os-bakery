"""RaspiOS upstream watcher.

Upstream index: https://downloads.raspberrypi.com/raspios_{arm64,lite_arm64}/
serves Apache directory listings of date-stamped subfolders
(`raspios_arm64-YYYY-MM-DD/`). Newest date == newest version. RaspiOS
publishes one arm64 image per variant — rpi3 / rpi4 / rpi5 share it.
"""

from __future__ import annotations

from .base import BaseWatcher


class RaspiOSWatcher(BaseWatcher):
    os_slug = "raspios"
    upstream_index_url = "https://downloads.raspberrypi.com/"

    variants = ("lite_arm64", "arm64")  # = lite / desktop in the catalog
    targets = ("rpi3", "rpi4", "rpi5")

    # TODO: fetch each variant index, parse the highest YYYY-MM-DD folder,
    # build CandidateRelease(version=date, channel='stable', codename=...)
    # and 6 images entries (3 Pi tiers × 2 variants).
