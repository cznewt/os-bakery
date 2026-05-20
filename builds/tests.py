from __future__ import annotations

import pytest
from django.utils import timezone

from builds.models import Artifact, BuildRequest, DownloadToken
from catalog.models import (
    Architecture,
    HardwareTarget,
    OperatingSystem,
    OSRelease,
    UpstreamImage,
)
from recipes.models import Recipe, RecipeVersion


@pytest.fixture
def basic_world(db):
    arch = Architecture.objects.create(slug="arm64", name="ARM64", family="arm", bits=64)
    hw = HardwareTarget.objects.create(
        slug="rpi5", name="Raspberry Pi 5", architecture=arch, boot_method="rpi"
    )
    os_ = OperatingSystem.objects.create(slug="batocera", name="Batocera", kind="retro")
    release = OSRelease.objects.create(
        operating_system=os_, version="41", channel="stable", is_default=True
    )
    upstream = UpstreamImage.objects.create(
        release=release,
        hardware_target=hw,
        source_url="https://example.com/batocera-41-rpi5.img.xz",
    )
    recipe = Recipe.objects.create(slug="family-arcade", name="Family Arcade", operating_system=os_)
    rv = RecipeVersion.objects.create(recipe=recipe, version="1.0.0", is_current=True)
    return {"hw": hw, "release": release, "upstream": upstream, "recipe": recipe, "rv": rv}


@pytest.mark.django_db
def test_download_token_validity(basic_world):
    build = BuildRequest.objects.create(
        recipe_version=basic_world["rv"],
        hardware_target=basic_world["hw"],
        upstream_image=basic_world["upstream"],
    )
    artifact = Artifact.objects.create(
        build=build,
        storage_key="x/y.img.xz",
        filename="y.img.xz",
        size_bytes=10,
        sha256="0" * 64,
    )
    token = DownloadToken.objects.create(
        artifact=artifact, expires_at=timezone.now() + timezone.timedelta(hours=1)
    )
    assert token.is_valid

    token.expires_at = timezone.now() - timezone.timedelta(seconds=1)
    token.save()
    assert not token.is_valid
