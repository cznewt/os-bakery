"""Tests for builds.provisioners.packer_arm_tools.

Pure-function tests over the preset mapping and env-builder — no Docker
involved. The actual `subprocess.run` call is exercised in integration tests
on a host with the packer-arm-tools image present.
"""

from __future__ import annotations

import json

import pytest
from django.utils import timezone

from builds.models import BuildRequest
from builds.provisioners import packer_arm_tools as pat
from catalog.models import (
    Architecture,
    HardwareTarget,
    OperatingSystem,
    OSRelease,
    UpstreamImage,
)
from recipes.models import Recipe, RecipeVersion


# ---------------------------------------------------------------------------
# Preset selection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key,expected",
    [
        # Direct hits
        (("rpi3", "raspios", "lite", False), "raspberry-pi-34-raspios-server-arm64"),
        (("rpi4", "ubuntu", "server", True), "raspberry-pi-34-ubuntu-server-salt-minion-arm64"),
        (("rpi4", "batocera", "", False), "raspberry-pi-4-batocera-desktop-arm64"),
        # Salt fallback to non-salt variant
        (("rpi4", "batocera", "", True), "raspberry-pi-4-batocera-desktop-arm64"),
        # Misses
        (("rpi5", "raspios", "lite", False), None),
        (("pc-amd64", "ubuntu", "server", False), None),
        (("rpi4", "haos", "", False), None),
        (("vm-qemu", "ubuntu", "server", False), None),
    ],
)
def test_select_preset(key, expected):
    assert pat.select_preset(*key) == expected


# ---------------------------------------------------------------------------
# Helpers for the env / command builder tests
# ---------------------------------------------------------------------------


@pytest.fixture
def basic_build(db):
    arch = Architecture.objects.create(slug="arm64", name="arm64", family="arm", bits=64)
    hw = HardwareTarget.objects.create(
        slug="rpi4", name="Raspberry Pi 4", architecture=arch, boot_method="rpi",
    )
    os_ = OperatingSystem.objects.create(slug="raspios", name="RaspiOS", kind="desktop")
    release = OSRelease.objects.create(
        operating_system=os_, version="2025-05-13", channel="stable", is_default=True,
    )
    upstream = UpstreamImage.objects.create(
        release=release,
        hardware_target=hw,
        variant="lite",
        source_url="https://example.com/raspios.img.xz",
        checksum_sha256="a" * 64,
    )
    recipe = Recipe.objects.create(slug="kiosk", name="Kiosk", operating_system=os_)
    rv = RecipeVersion.objects.create(recipe=recipe, version="1.0.0", is_current=True)
    build = BuildRequest.objects.create(
        recipe_version=rv,
        hardware_target=hw,
        upstream_image=upstream,
        label="lab-1",
        option_values={
            "hostname": "lab-1",
            "wifi_ssid": "guests",
            "wifi_psk": "secret",
            "install_salt_minion": True,
            "salt_pub_key": "fakepub",
            "salt_priv_key": "fakepriv",
        },
    )
    return build


# ---------------------------------------------------------------------------
# build_image_variables
# ---------------------------------------------------------------------------


def test_build_image_variables_minimal(basic_build):
    basic_build.option_values = {"hostname": "lab-1"}
    basic_build.save()
    vars_ = pat.build_image_variables(basic_build, with_salt=False)
    assert vars_ == {
        "FILE_URL": "https://example.com/raspios.img.xz",
        "FILE_CHECKSUM": "a" * 64,
        "HOSTNAME": "lab-1",
    }


def test_build_image_variables_with_wifi_and_salt(basic_build):
    vars_ = pat.build_image_variables(basic_build, with_salt=True)
    assert vars_["WPA_ESSID"] == "guests"
    assert vars_["WPA_PASSWORD"] == "secret"
    assert vars_["WPA_COUNTRY"] == "DE"  # default
    assert vars_["SALT_MINION"] == "lab-1"
    assert vars_["SALT_PUB_KEY"] == "fakepub"
    assert vars_["SALT_PRIV_KEY"] == "fakepriv"


def test_hostname_falls_back_to_label_then_id(basic_build):
    basic_build.option_values = {}
    basic_build.save()
    vars_ = pat.build_image_variables(basic_build, with_salt=False)
    assert vars_["HOSTNAME"] == "lab-1"  # falls back to label

    basic_build.label = ""
    basic_build.save()
    vars_ = pat.build_image_variables(basic_build, with_salt=False)
    assert vars_["HOSTNAME"].startswith("osbakery-")


# ---------------------------------------------------------------------------
# build_docker_command
# ---------------------------------------------------------------------------


def test_build_docker_command_shape():
    cmd = pat.build_docker_command(
        image="docker.io/cznewt/packer-arm-tools:latest",
        preset="raspberry-pi-34-raspios-server-arm64",
        image_name="osbakery-abc",
        build_path="/tmp/build",
        image_variables={"FILE_URL": "https://x/y.img.xz", "HOSTNAME": "lab-1"},
    )
    assert cmd[:5] == ["docker", "run", "-i", "--rm=true", "--privileged"]
    assert "-v" in cmd and "/dev:/dev" in cmd
    assert "/tmp/build:/build" in cmd
    # Env entries should encode the variables JSON deterministically.
    env_pairs = [cmd[i + 1] for i, x in enumerate(cmd) if x == "-e"]
    by_key = dict(p.split("=", 1) for p in env_pairs)
    assert by_key["BUILD_PATH"] == "/build"
    assert by_key["IMAGE_NAME"] == "osbakery-abc"
    assert by_key["IMAGE_TEMPLATE"] == "raspberry-pi-34-raspios-server-arm64"
    assert json.loads(by_key["IMAGE_VARIABLES"]) == {
        "FILE_URL": "https://x/y.img.xz",
        "HOSTNAME": "lab-1",
    }
    # Trailing image + entrypoint command
    assert cmd[-2] == "docker.io/cznewt/packer-arm-tools:latest"
    assert cmd[-1] == "packer-build-arm-image"
