"""Ubuntu upstream watcher.

https://cloud-images.ubuntu.com/releases/ lists version-numbered subdirs
(22.04, 24.04, 24.10, 25.04, 26.04, …). LTS = an X.04 release where X is even.
"""

from __future__ import annotations

import re

from .base import BaseWatcher, CandidateRelease, http_get

_VER = re.compile(r"\b(\d{2})\.(\d{2})/")


class UbuntuWatcher(BaseWatcher):
    os_slug = "ubuntu"
    upstream_index_url = "https://cloud-images.ubuntu.com/releases/"

    def latest_releases(self) -> list[CandidateRelease]:
        html = http_get(self.upstream_index_url)
        versions = sorted({f"{m.group(1)}.{m.group(2)}" for m in _VER.finditer(html)})
        out: list[CandidateRelease] = []
        for v in versions:
            year, month = v.split(".")
            is_lts = month == "04" and int(year) % 2 == 0
            out.append(CandidateRelease(
                os_slug=self.os_slug,
                version=v,
                channel="lts" if is_lts else "stable",
                release_notes_url=f"https://wiki.ubuntu.com/Releases",
            ))
        return out
