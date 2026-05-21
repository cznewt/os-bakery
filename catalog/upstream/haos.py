"""HAOS upstream watcher.

HAOS publishes via GitHub Releases:
https://api.github.com/repos/home-assistant/operating-system/releases

The latest stable can be fetched with a single API call. Each release
attaches per-target assets (`haos_rpi4-64-X.Y.img.xz`, `haos_rpi5-64-X.Y.img.xz`,
`haos_generic-x86-64-X.Y.img.xz`, …).
"""

from __future__ import annotations

from .base import BaseWatcher


class HAOSWatcher(BaseWatcher):
    os_slug = "haos"
    upstream_index_url = (
        "https://api.github.com/repos/home-assistant/operating-system/releases/latest"
    )

    # Mapping of HardwareTarget slug → GitHub asset platform fragment.
    platform_for_target = {
        "rpi4": "rpi4-64",
        "rpi5": "rpi5-64",
        "pc-amd64": "generic-x86-64",
    }

    # TODO: GET upstream_index_url, take .tag_name as the version, walk
    # .assets to extract per-target download_url. Return a single
    # CandidateRelease with `images` populated.
