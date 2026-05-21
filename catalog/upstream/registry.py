"""Watcher registry: OS slug -> watcher class.

Wires the per-OS watcher modules into a single lookup so the poll command
doesn't have to know about each module by name.
"""

from __future__ import annotations

from .base import BaseWatcher
from .batocera import BatoceraWatcher
from .haos import HAOSWatcher
from .raspios import RaspiOSWatcher
from .ubuntu import UbuntuWatcher

WATCHERS: dict[str, type[BaseWatcher]] = {
    BatoceraWatcher.os_slug: BatoceraWatcher,
    UbuntuWatcher.os_slug: UbuntuWatcher,
    RaspiOSWatcher.os_slug: RaspiOSWatcher,
    HAOSWatcher.os_slug: HAOSWatcher,
}


def get_watcher(os_slug: str) -> BaseWatcher | None:
    cls = WATCHERS.get(os_slug)
    return cls() if cls else None
