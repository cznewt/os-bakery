"""Smoke tests for the catalog app.

Real coverage will accrue as the sync jobs and management commands take shape.
"""

from __future__ import annotations

import pytest

from catalog.models import Architecture, HardwareTarget


@pytest.mark.django_db
def test_hardware_target_round_trip() -> None:
    arch = Architecture.objects.create(slug="arm64", name="ARM 64-bit", family="arm", bits=64)
    target = HardwareTarget.objects.create(
        slug="rpi5",
        name="Raspberry Pi 5",
        architecture=arch,
        boot_method="rpi",
        soc="BCM2712",
    )
    assert str(target) == "Raspberry Pi 5 (arm64)"
    assert arch.hardware_targets.count() == 1
