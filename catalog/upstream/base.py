"""Abstract base for per-OS upstream watchers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class CandidateRelease:
    """A potential new OSRelease detected by a watcher.

    Watchers return CandidateRelease values; the poll command converts them
    into get_or_create() calls against ``catalog.OSRelease`` (and may also
    seed UpstreamImage rows when the watcher knows the per-target URLs).
    """

    os_slug: str                       # e.g. "batocera"
    version: str                       # e.g. "42", "24.10", "2025-06-15"
    channel: str = "stable"            # OSRelease.Channel value
    codename: str = ""                 # e.g. "Bookworm", "Noble"
    released_on: date | None = None
    release_notes_url: str = ""
    # Per-target image URLs the watcher already happens to know about.
    # Keyed by (hardware_target_slug, variant) → source_url.
    images: dict[tuple[str, str], str] = field(default_factory=dict)


class BaseWatcher:
    """Override `latest_releases()` and (optionally) `mirror_url_for()`."""

    #: The OperatingSystem.slug this watcher handles. Required on subclasses.
    os_slug: str = ""

    #: The upstream index URL that should be polled. Documentation-grade —
    #: subclasses fetch from here in their implementation.
    upstream_index_url: str = ""

    def latest_releases(self) -> list[CandidateRelease]:
        """Return any releases newer than what's already in the DB.

        Default returns []. Subclasses fetch + parse the upstream index and
        emit a CandidateRelease per new version they see.
        """
        return []

    def mirror_url_for(self, source_url: str) -> str | None:
        """Translate an upstream URL into a local-mirror URL, or None.

        Returning None means "no mirror configured / not in the mirror" —
        the caller should keep using ``source_url``.
        """
        return None
