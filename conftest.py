"""Shared pytest configuration / fixtures.

Lives at the repo root so every test module picks it up automatically.
"""

from __future__ import annotations

import pytest
from django.db.models.signals import post_save


@pytest.fixture(autouse=True)
def _disable_build_dispatch_signal():
    """Disconnect the BuildRequest post_save → Celery dispatch during tests.

    Without this every test that creates a BuildRequest tries to talk to
    Redis (and hangs for 20 retries before failing). The signal is reconnected
    once the test finishes.
    """
    from builds import signals  # noqa: F401 — registers the receiver on import
    from builds.models import BuildRequest
    from builds.signals import enqueue_new_build_requests

    post_save.disconnect(enqueue_new_build_requests, sender=BuildRequest)
    try:
        yield
    finally:
        post_save.connect(enqueue_new_build_requests, sender=BuildRequest)
