from django.contrib import admin
from django.utils.html import format_html

from .models import Artifact, BuildEvent, BuildRequest, DownloadToken


class BuildEventInline(admin.TabularInline):
    model = BuildEvent
    extra = 0
    fields = ("at", "level", "phase", "message")
    readonly_fields = fields
    can_delete = False


@admin.register(BuildRequest)
class BuildRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "recipe_version",
        "hardware_target",
        "status",
        "requester",
        "queued_at",
        "duration_display",
    )
    list_filter = ("status", "hardware_target", "recipe_version__recipe")
    search_fields = ("id", "label", "requester__username")
    readonly_fields = (
        "id",
        "queued_at",
        "started_at",
        "finished_at",
        "celery_task_id",
        "duration_display",
    )
    inlines = [BuildEventInline]

    @admin.display(description="Duration")
    def duration_display(self, obj: BuildRequest) -> str:
        if obj.duration is None:
            return "—"
        return str(obj.duration).split(".")[0]


@admin.register(Artifact)
class ArtifactAdmin(admin.ModelAdmin):
    list_display = ("filename", "build", "format", "size_bytes", "sha256_short", "expires_at")
    search_fields = ("filename", "sha256", "build__id")
    readonly_fields = ("sha256", "size_bytes", "media_type", "storage_key", "created_at")

    @admin.display(description="sha256")
    def sha256_short(self, obj: Artifact) -> str:
        return format_html("<code>{}…</code>", obj.sha256[:12]) if obj.sha256 else "—"


@admin.register(DownloadToken)
class DownloadTokenAdmin(admin.ModelAdmin):
    list_display = ("artifact", "expires_at", "use_count", "max_uses", "issued_to", "revoked_at")
    list_filter = ("revoked_at",)
    search_fields = ("token", "note", "artifact__filename")
    readonly_fields = ("token", "use_count", "last_used_at", "created_at")
