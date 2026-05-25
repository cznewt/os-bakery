"""Batocera upstream watcher — scrapes the public changelog.

https://batocera.org/changelog lists rows like::

    43 - 2026/05/08 - Glasswing
    42 - 2025/10/12 - Papilio Ulysses

i.e. ``<version> - YYYY/MM/DD - <codename>``. We parse those into
CandidateRelease rows; the poll command dedups against the DB.
"""

from __future__ import annotations

import datetime
import re

from .base import BaseWatcher, CandidateRelease, http_get

_ROW = re.compile(r"\b(\d{2}) - (20\d{2})/(\d{2})/(\d{2}) - ([A-Za-z][A-Za-z .-]+)")


class BatoceraWatcher(BaseWatcher):
    os_slug = "batocera"
    upstream_index_url = "https://batocera.org/changelog"

    def latest_releases(self) -> list[CandidateRelease]:
        html = http_get(self.upstream_index_url)
        out: list[CandidateRelease] = []
        seen: set[str] = set()
        for m in _ROW.finditer(html):
            version = m.group(1)
            if version in seen:
                continue
            seen.add(version)
            out.append(CandidateRelease(
                os_slug=self.os_slug,
                version=version,
                channel="stable",
                codename=m.group(5).strip(),
                released_on=datetime.date(int(m.group(2)), int(m.group(3)), int(m.group(4))),
                release_notes_url=self.upstream_index_url,
            ))
        return out
