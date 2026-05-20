from rest_framework.routers import DefaultRouter

from .views import BuildRequestViewSet

router = DefaultRouter()
router.register(r"", BuildRequestViewSet, basename="build")

urlpatterns = router.urls
