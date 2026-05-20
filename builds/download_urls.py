from django.urls import path

from .views import download_artifact

urlpatterns = [
    path("<str:token>/", download_artifact, name="download-artifact"),
]
