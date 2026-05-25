"""HAOS upstream watcher — latest GitHub release.

GET https://api.github.com/repos/home-assistant/operating-system/releases/latest
and use ``.tag_name`` as the version.
"""

from __future__ import annotations

import json

from .base import BaseWatcher, CandidateRelease, http_get


class HAOSWatcher(BaseWatcher):
    os_slug = "haos"
    upstream_index_url = (
        "https://api.github.com/repos/home-assistant/operating-system/releases/latest"
    )

    def latest_releases(self) -> list[CandidateRelease]:
        body = http_get(self.upstream_index_url)
        if not body:
            return []
        try:
            rel = json.loads(body)
        except json.JSONDecodeError:
            return []
        tag = (rel.get("tag_name") or "").lstrip("v")
        if not tag:
            return []
        return [CandidateRelease(
            os_slug=self.os_slug,
            version=tag,
            channel="stable",
            release_notes_url=rel.get("html_url", ""),
        )]
