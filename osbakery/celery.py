"""Celery application for os-bakery.

Builds run on the ``builds`` queue; everything else uses the default queue.
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "osbakery.settings")

app = Celery("osbakery")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> None:
    print(f"Request: {self.request!r}")
