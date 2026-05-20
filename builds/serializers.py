from rest_framework import serializers

from catalog.models import HardwareTarget, UpstreamImage
from recipes.models import Recipe, RecipeVersion

from .models import Artifact, BuildEvent, BuildRequest, DownloadToken


class BuildEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuildEvent
        fields = ["at", "level", "phase", "message", "data"]


class ArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Artifact
        fields = [
            "filename",
            "format",
            "size_bytes",
            "sha256",
            "media_type",
            "created_at",
            "expires_at",
        ]


class DownloadTokenSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = DownloadToken
        fields = [
            "token",
            "expires_at",
            "max_uses",
            "use_count",
            "revoked_at",
            "download_url",
        ]
        read_only_fields = fields

    def get_download_url(self, obj: DownloadToken) -> str:
        request = self.context.get("request")
        path = f"/d/{obj.token}/"
        return request.build_absolute_uri(path) if request else path


class BuildRequestSerializer(serializers.ModelSerializer):
    artifact = ArtifactSerializer(read_only=True)
    events = BuildEventSerializer(many=True, read_only=True)
    tokens = serializers.SerializerMethodField()

    recipe_slug = serializers.CharField(write_only=True, required=False)
    recipe_version = serializers.PrimaryKeyRelatedField(
        queryset=RecipeVersion.objects.all(), required=False
    )
    hardware_target_slug = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=HardwareTarget.objects.all(),
        source="hardware_target",
        write_only=True,
    )

    class Meta:
        model = BuildRequest
        fields = [
            "id",
            "requester",
            "recipe_slug",
            "recipe_version",
            "hardware_target_slug",
            "hardware_target",
            "upstream_image",
            "option_values",
            "label",
            "status",
            "queued_at",
            "started_at",
            "finished_at",
            "failure_reason",
            "artifact",
            "events",
            "tokens",
        ]
        read_only_fields = [
            "id",
            "requester",
            "hardware_target",
            "upstream_image",
            "status",
            "queued_at",
            "started_at",
            "finished_at",
            "failure_reason",
        ]

    def get_tokens(self, obj: BuildRequest):
        if not hasattr(obj, "artifact"):
            return []
        return DownloadTokenSerializer(
            obj.artifact.tokens.all(), many=True, context=self.context
        ).data

    def create(self, validated_data):
        recipe_slug = validated_data.pop("recipe_slug", None)
        recipe_version = validated_data.get("recipe_version")
        if recipe_version is None and recipe_slug:
            recipe = Recipe.objects.get(slug=recipe_slug)
            recipe_version = recipe.current_version
            if recipe_version is None:
                raise serializers.ValidationError(
                    f"Recipe '{recipe_slug}' has no current version."
                )
            validated_data["recipe_version"] = recipe_version
        elif recipe_version is None:
            raise serializers.ValidationError("Either recipe_slug or recipe_version is required.")

        hw = validated_data["hardware_target"]
        recipe = validated_data["recipe_version"].recipe
        release = recipe.pinned_release or recipe.operating_system.releases.filter(
            is_default=True
        ).first()
        if release is None:
            raise serializers.ValidationError(
                f"No default release set for {recipe.operating_system.slug}."
            )
        try:
            upstream = UpstreamImage.objects.get(release=release, hardware_target=hw)
        except UpstreamImage.DoesNotExist as exc:
            raise serializers.ValidationError(
                f"No upstream image for {release} on {hw.slug}."
            ) from exc
        validated_data["upstream_image"] = upstream

        return super().create(validated_data)
