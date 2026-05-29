from django.contrib import admin

from .models import Cluster, Integration, Node, Tenant, ZerotierIdentity


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "owner", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("slug", "name")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("members",)


@admin.register(Cluster)
class ClusterAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "tenant", "is_active", "created_at")
    list_filter = ("is_active", "tenant")
    search_fields = ("slug", "name", "tenant__slug")
    autocomplete_fields = ("tenant",)


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "cluster", "preset", "hardware_target",
                    "is_active", "created_at")
    list_filter = ("is_active", "cluster__tenant", "cluster", "preset")
    search_fields = ("slug", "name", "hostname", "cluster__slug")
    autocomplete_fields = ("cluster", "preset", "hardware_target", "upstream_image")


@admin.register(Integration)
class IntegrationAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "tenant", "url", "is_active", "created_at")
    list_filter = ("type", "is_active", "tenant")
    search_fields = ("name", "url", "tenant__slug")
    autocomplete_fields = ("tenant",)


@admin.register(ZerotierIdentity)
class ZerotierIdentityAdmin(admin.ModelAdmin):
    list_display = ("node", "network_id", "member_id", "updated_at")
    list_filter = ("node__cluster__tenant", "node__cluster")
    search_fields = ("node__slug", "network_id", "member_id")
    autocomplete_fields = ("node",)
