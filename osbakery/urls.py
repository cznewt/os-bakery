from django.contrib import admin
from django.urls import include, path

from .views import base_images, home

urlpatterns = [
    path("", home, name="home"),
    path("images/", base_images, name="base_images"),
    path("admin/", admin.site.urls),
    path("api/catalog/", include("catalog.urls")),
    path("api/recipes/", include("recipes.urls")),
    path("api/builds/", include("builds.urls")),
    path("d/", include("builds.download_urls")),
]
