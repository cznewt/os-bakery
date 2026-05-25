from django.contrib import admin

from .models import (
    Architecture,
    HardwareTarget,
    OperatingSystem,
    OSRelease,
    Provisioner,
    UpstreamImage,
)


@admin.register(Provisioner)
class ProvisionerAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "is_default", "is_active")
    list_filter = ("is_default", "is_active")
    search_fields = ("slug", "name")


@admin.register(Architecture)
class ArchitectureAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "family", "bits")
    list_filter = ("family",)
    search_fields = ("slug", "name")


@admin.register(HardwareTarget)
class HardwareTargetAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "architecture", "boot_method", "soc", "is_active")
    list_filter = ("architecture", "boot_method", "is_active")
    search_fields = ("slug", "name", "soc")


@admin.register(OperatingSystem)
class OperatingSystemAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "kind", "vendor", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("slug", "name", "vendor")


class UpstreamImageInline(admin.TabularInline):
    model = UpstreamImage
    extra = 0
    fields = ("hardware_target", "variant", "format", "source_url", "is_synced")
    readonly_fields = ("is_synced",)


@admin.register(OSRelease)
class OSReleaseAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "operating_system",
        "version",
        "channel",
        "released_on",
        "end_of_life_on",
        "is_default",
    )
    list_filter = ("operating_system", "channel", "is_default")
    search_fields = ("version", "codename")
    inlines = [UpstreamImageInline]


@admin.register(UpstreamImage)
class UpstreamImageAdmin(admin.ModelAdmin):
    list_display = (
        "release",
        "hardware_target",
        "variant",
        "format",
        "size_bytes",
        "is_synced",
        "last_synced_at",
    )
    list_filter = ("format", "release__operating_system", "hardware_target")
    search_fields = ("source_url", "variant", "checksum_sha256")
    readonly_fields = ("checksum_sha256", "size_bytes", "last_synced_at")
