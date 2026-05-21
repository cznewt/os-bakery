"""Upstream-release watchers.

Each :class:`BaseWatcher` subclass knows how to poll a single OS vendor's
release index and report new versions. The catalog management command
``poll_upstream`` iterates the active OperatingSystem rows, looks up the
matching watcher, and prints / persists what's new.

This is intentionally a skeleton — each per-OS watcher's `latest_releases()`
returns an empty list until somebody fills in the actual scraping. The
shape (registry + dataclass return value) is the API the rest of the system
can depend on.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import BaseWatcher, CandidateRelease
from .registry import WATCHERS, get_watcher

__all__ = ["BaseWatcher", "CandidateRelease", "WATCHERS", "get_watcher"]
