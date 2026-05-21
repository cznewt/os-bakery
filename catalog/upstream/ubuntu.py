"""Ubuntu upstream watcher.

Canonical cuts predictable releases:
- LTS even years: 24.04, 26.04, ...
- Interim releases: 24.10, 25.04, 25.10, ...
- Point releases on LTS: 24.04.1, 24.04.2, ...

Index URLs of interest:
- https://cdimage.ubuntu.com/releases/ — official ISOs / preinstalled
- https://cloud-images.ubuntu.com/releases/ — cloud-image .img / .qcow2

Both list version-numbered subdirectories. Parsing one is enough since the
release numbers align.
"""

from __future__ import annotations

from .base import BaseWatcher


class UbuntuWatcher(BaseWatcher):
    os_slug = "ubuntu"
    upstream_index_url = "https://cdimage.ubuntu.com/releases/"

    # TODO: fetch the index, list NN.NN[/.NN]/ subdirs, compare to existing
    # OSRelease rows, emit CandidateReleases for anything new. Channel is
    # `lts` for X.04 versions where X is even, `stable` otherwise.
