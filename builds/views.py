from __future__ import annotations

from django.core.files.storage import storages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from .models import BuildRequest, DownloadToken
from .serializers import BuildRequestSerializer


class BuildRequestViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = (
        BuildRequest.objects.select_related(
            "recipe_version__recipe__operating_system",
            "hardware_target__architecture",
            "upstream_image__release",
            "requester",
        )
        .prefetch_related("events", "artifact__tokens")
    )
    serializer_class = BuildRequestSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filterset_fields = ["status", "hardware_target__slug", "recipe_version__recipe__slug"]

    def perform_create(self, serializer) -> None:
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(requester=user)


def download_artifact(request, token: str):
    """Serve the artifact behind a one-time-ish bearer token.

    Returns 404 for revoked, expired, or over-used tokens (no leak of which it
    was). On success, increments the use counter and streams the file from the
    artifacts storage backend.
    """
    dl = get_object_or_404(DownloadToken, token=token)
    if not dl.is_valid:
        raise Http404("Download not available.")

    artifact = dl.artifact
    if artifact.is_expired:
        raise Http404("Artifact expired.")

    dl.use_count += 1
    dl.last_used_at = timezone.now()
    dl.save(update_fields=["use_count", "last_used_at"])

    storage = storages["artifacts"]
    file = storage.open(artifact.storage_key, "rb")
    response = FileResponse(file, as_attachment=True, filename=artifact.filename)
    response["Content-Type"] = artifact.media_type
    response["Content-Length"] = str(artifact.size_bytes)
    response["X-Checksum-SHA256"] = artifact.sha256
    return response
