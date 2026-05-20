from django.apps import AppConfig


class BuildsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "builds"
    verbose_name = "Image Builds"

    def ready(self) -> None:  # noqa: D401 - Django hook
        from . import signals  # noqa: F401  (register handlers)
