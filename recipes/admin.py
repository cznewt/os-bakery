from django.contrib import admin

from .models import Recipe, RecipeOption, RecipeVersion


class RecipeOptionInline(admin.TabularInline):
    model = RecipeOption
    extra = 0
    fields = ("sort_order", "key", "label", "kind", "required", "default")


class RecipeVersionInline(admin.TabularInline):
    model = RecipeVersion
    extra = 0
    fields = ("version", "is_current", "salt_states", "changelog")
    readonly_fields = ("created_at",)


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "operating_system", "visibility", "status", "owner")
    list_filter = ("operating_system", "visibility", "status")
    search_fields = ("slug", "name", "summary")
    filter_horizontal = ("supported_hardware",)
    inlines = [RecipeVersionInline, RecipeOptionInline]


@admin.register(RecipeVersion)
class RecipeVersionAdmin(admin.ModelAdmin):
    list_display = ("recipe", "version", "is_current", "created_at")
    list_filter = ("recipe", "is_current")
    search_fields = ("recipe__slug", "version")


@admin.register(RecipeOption)
class RecipeOptionAdmin(admin.ModelAdmin):
    list_display = ("recipe", "key", "label", "kind", "required")
    list_filter = ("kind", "required", "recipe")
    search_fields = ("key", "label", "recipe__slug")
