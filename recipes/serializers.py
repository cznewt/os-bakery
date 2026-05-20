from rest_framework import serializers

from .models import Recipe, RecipeOption, RecipeVersion


class RecipeOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecipeOption
        fields = ["key", "label", "help_text", "kind", "default", "choices", "required", "sort_order"]


class RecipeVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecipeVersion
        fields = [
            "id",
            "version",
            "is_current",
            "salt_states",
            "pillar_overrides",
            "changelog",
            "created_at",
        ]


class RecipeSerializer(serializers.ModelSerializer):
    operating_system = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    supported_hardware = serializers.SlugRelatedField(
        slug_field="slug", many=True, read_only=True
    )
    options = RecipeOptionSerializer(many=True, read_only=True)
    versions = RecipeVersionSerializer(many=True, read_only=True)
    current_version = RecipeVersionSerializer(read_only=True)

    class Meta:
        model = Recipe
        fields = [
            "slug",
            "name",
            "summary",
            "description",
            "operating_system",
            "pinned_release",
            "supported_hardware",
            "visibility",
            "status",
            "tags",
            "options",
            "versions",
            "current_version",
        ]
