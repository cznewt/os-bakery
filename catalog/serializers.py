from rest_framework import serializers

from .models import (
    Architecture,
    HardwareTarget,
    OperatingSystem,
    OSRelease,
    UpstreamImage,
)


class ArchitectureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Architecture
        fields = ["slug", "name", "family", "bits", "description"]


class HardwareTargetSerializer(serializers.ModelSerializer):
    architecture = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = HardwareTarget
        fields = ["slug", "name", "architecture", "boot_method", "soc", "is_active"]


class OperatingSystemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperatingSystem
        fields = ["slug", "name", "vendor", "kind", "homepage", "summary", "is_active"]


class OSReleaseSerializer(serializers.ModelSerializer):
    operating_system = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = OSRelease
        fields = [
            "id",
            "operating_system",
            "version",
            "codename",
            "channel",
            "released_on",
            "end_of_life_on",
            "is_default",
        ]


class UpstreamImageSerializer(serializers.ModelSerializer):
    release = OSReleaseSerializer(read_only=True)
    hardware_target = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = UpstreamImage
        fields = [
            "id",
            "release",
            "hardware_target",
            "variant",
            "format",
            "source_url",
            "checksum_sha256",
            "size_bytes",
            "local_path",
            "last_synced_at",
        ]
