from django.contrib import admin

from .models import PackerTemplate, SaltFormula


@admin.register(PackerTemplate)
class PackerTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "slug",
        "name",
        "operating_system",
        "hardware_target",
        "status",
        "last_run_at",
    )
    list_filter = ("operating_system", "hardware_target", "status")
    search_fields = ("slug", "name", "relative_path")
    filter_horizontal = ("produces",)


@admin.register(SaltFormula)
class SaltFormulaAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "relative_path", "is_internal")
    list_filter = ("is_internal", "operating_systems")
    search_fields = ("slug", "name", "relative_path")
    filter_horizontal = ("operating_systems", "used_by")
