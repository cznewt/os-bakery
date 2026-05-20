from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/catalog/", include("catalog.urls")),
    path("api/recipes/", include("recipes.urls")),
    path("api/builds/", include("builds.urls")),
    path("d/", include("builds.download_urls")),
]
