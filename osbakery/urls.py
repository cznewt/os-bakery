from django.contrib import admin
from django.urls import include, path

from .views import bake_index, bake_recipe, base_images, devices, home

urlpatterns = [
    path("", home, name="home"),
    path("devices/", devices, name="devices"),
    path("images/", base_images, name="base_images"),
    path("bake/", bake_index, name="bake_index"),
    path("bake/<slug:slug>/", bake_recipe, name="bake_recipe"),
    path("admin/", admin.site.urls),
    path("api/catalog/", include("catalog.urls")),
    path("api/recipes/", include("recipes.urls")),
    path("api/builds/", include("builds.urls")),
    path("d/", include("builds.download_urls")),
]
