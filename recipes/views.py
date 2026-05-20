from rest_framework import viewsets

from .models import Recipe
from .serializers import RecipeSerializer


class RecipeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Recipe.objects.select_related("operating_system", "pinned_release")
        .prefetch_related("supported_hardware", "options", "versions")
    )
    serializer_class = RecipeSerializer
    lookup_field = "slug"
    filterset_fields = ["operating_system__slug", "status", "visibility"]
