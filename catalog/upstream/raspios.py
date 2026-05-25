"""RaspiOS upstream watcher.

Index pages under https://downloads.raspberrypi.com/raspios_lite_arm64/images/
list date-stamped folders (`raspios_lite_arm64-YYYY-MM-DD/`). Newest date ==
newest version; the codename (bookworm/trixie) is in the image filename.
"""

from __future__ import annotations

import datetime
import re

from .base import BaseWatcher, CandidateRelease, http_get

_DIR = re.compile(r"raspios_lite_arm64-(\d{4})-(\d{2})-(\d{2})")
_CODENAME = re.compile(r"\d{4}-\d{2}-\d{2}-raspios-([a-z]+)-arm64-lite\.img")


class RaspiOSWatcher(BaseWatcher):
    os_slug = "raspios"
    upstream_index_url = "https://downloads.raspberrypi.com/raspios_lite_arm64/images/"

    def latest_releases(self) -> list[CandidateRelease]:
        html = http_get(self.upstream_index_url)
        dates = {m.group(0).split("-", 1)[1] for m in _DIR.finditer(html)}
        if not dates:
            return []
        latest = max(dates)  # YYYY-MM-DD strings sort chronologically
        # Fetch the folder to read the codename out of the image filename.
        folder = http_get(f"{self.upstream_index_url}raspios_lite_arm64-{latest}/")
        cm = _CODENAME.search(folder)
        codename = cm.group(1).capitalize() if cm else ""
        y, mo, d = (int(x) for x in latest.split("-"))
        return [CandidateRelease(
            os_slug=self.os_slug,
            version=latest,
            channel="stable",
            codename=codename,
            released_on=datetime.date(y, mo, d),
            release_notes_url="https://www.raspberrypi.com/software/operating-systems/",
        )]
