from django.contrib import admin

from .models import Cluster, Node, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "owner", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("slug", "name")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("members",)


@admin.register(Cluster)
class ClusterAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "tenant", "kind", "is_active", "created_at")
    list_filter = ("kind", "is_active", "tenant")
    search_fields = ("slug", "name", "tenant__slug")
    autocomplete_fields = ("tenant",)


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "cluster", "preset", "hardware_target",
                    "is_active", "created_at")
    list_filter = ("is_active", "cluster__tenant", "cluster", "preset")
    search_fields = ("slug", "name", "hostname", "cluster__slug")
    autocomplete_fields = ("cluster", "preset", "hardware_target", "upstream_image")
