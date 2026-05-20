from rest_framework.routers import DefaultRouter

from .views import (
    ArchitectureViewSet,
    HardwareTargetViewSet,
    OperatingSystemViewSet,
    OSReleaseViewSet,
    UpstreamImageViewSet,
)

router = DefaultRouter()
router.register(r"architectures", ArchitectureViewSet, basename="architecture")
router.register(r"hardware-targets", HardwareTargetViewSet, basename="hardware-target")
router.register(r"operating-systems", OperatingSystemViewSet, basename="operating-system")
router.register(r"releases", OSReleaseViewSet, basename="release")
router.register(r"upstream-images", UpstreamImageViewSet, basename="upstream-image")

urlpatterns = router.urls
