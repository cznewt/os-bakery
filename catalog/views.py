from rest_framework import viewsets

from .models import (
    Architecture,
    HardwareTarget,
    OperatingSystem,
    OSRelease,
    UpstreamImage,
)
from .serializers import (
    ArchitectureSerializer,
    HardwareTargetSerializer,
    OperatingSystemSerializer,
    OSReleaseSerializer,
    UpstreamImageSerializer,
)


class ArchitectureViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Architecture.objects.all()
    serializer_class = ArchitectureSerializer
    lookup_field = "slug"


class HardwareTargetViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = HardwareTarget.objects.select_related("architecture")
    serializer_class = HardwareTargetSerializer
    lookup_field = "slug"
    filterset_fields = ["architecture__slug", "boot_method", "is_active"]


class OperatingSystemViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = OperatingSystem.objects.all()
    serializer_class = OperatingSystemSerializer
    lookup_field = "slug"
    filterset_fields = ["kind", "is_active"]


class OSReleaseViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = OSRelease.objects.select_related("operating_system")
    serializer_class = OSReleaseSerializer
    filterset_fields = ["operating_system__slug", "channel", "is_default"]


class UpstreamImageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UpstreamImage.objects.select_related("release__operating_system", "hardware_target")
    serializer_class = UpstreamImageSerializer
    filterset_fields = ["release__operating_system__slug", "hardware_target__slug", "format"]
