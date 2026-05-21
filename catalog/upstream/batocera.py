"""Batocera upstream watcher.

Upstream index: per-platform `last/` directories under
https://updates.batocera.org/{bcm2710,bcm2711,bcm2712,x86_64}/stable/last/
contain a single image plus a `latest_version` text file. A small HTTP HEAD
+ filename parse is enough to extract the version number.
"""

from __future__ import annotations

from .base import BaseWatcher, CandidateRelease


class BatoceraWatcher(BaseWatcher):
    os_slug = "batocera"
    upstream_index_url = "https://updates.batocera.org/"

    # Platform key per HardwareTarget the catalog knows about.
    platforms = {
        "rpi3": "bcm2710",
        "rpi4": "bcm2711",
        "rpi5": "bcm2712",
        "pc-amd64": "x86_64",
    }

    def latest_releases(self) -> list[CandidateRelease]:
        # TODO: fetch one URL per platform from `upstream_index_url`, parse
        # the version out of the served filename, dedup, return a single
        # CandidateRelease with per-target `images` filled in. Skeleton
        # returns [] so the polling job is a no-op until implemented.
        return []
