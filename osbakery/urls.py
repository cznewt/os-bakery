from django.contrib import admin
from django.urls import include, path

from .views import (
    baked_images,
    bake_index,
    bake_recipe,
    base_images,
    cluster_detail,
    clusters,
    devices,
    doc_page,
    docs_index,
    download_base_image,
    home,
    sync_base_image,
)

urlpatterns = [
    path("", home, name="home"),
    path("devices/", devices, name="devices"),
    path("images/", base_images, name="base_images"),
    path("baked/", baked_images, name="baked_images"),
    path("clusters/", clusters, name="clusters"),
    path("clusters/<slug:slug>/", cluster_detail, name="cluster_detail"),
    path("images/<int:pk>/download/", download_base_image, name="download_base_image"),
    path("images/<int:pk>/sync/", sync_base_image, name="sync_base_image"),
    path("bake/", bake_index, name="bake_index"),
    path("bake/<slug:slug>/", bake_recipe, name="bake_recipe"),
    path("docs/", docs_index, name="docs_index"),
    path("docs/<slug:slug>/", doc_page, name="doc_page"),
    path("admin/", admin.site.urls),
    path("api/catalog/", include("catalog.urls")),
    path("api/recipes/", include("recipes.urls")),
    path("api/builds/", include("builds.urls")),
    path("d/", include("builds.download_urls")),
]
