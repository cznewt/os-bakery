"""Django settings for the os-bakery project.

Settings are read from environment variables (with sensible defaults for local
development). See `.env.example` for the documented surface.
"""

from __future__ import annotations

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, True),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-secret-change-me")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "django_filters",
    "django_extensions",
    # Local
    "catalog.apps.CatalogConfig",
    "recipes.apps.RecipesConfig",
    "builds.apps.BuildsConfig",
    "infra.apps.InfraConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "osbakery.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "osbakery" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "osbakery.wsgi.application"
ASGI_APPLICATION = "osbakery.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    ),
}

# ---------------------------------------------------------------------------
# Auth / i18n / static
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {
    "builds.tasks.*": {"queue": "builds"},
}
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# ---------------------------------------------------------------------------
# Storage for produced image artifacts
# ---------------------------------------------------------------------------

ARTIFACT_STORAGE_BACKEND = env("ARTIFACT_STORAGE_BACKEND", default="local")
ARTIFACT_STORAGE_ROOT = Path(
    env("ARTIFACT_STORAGE_ROOT", default=str(BASE_DIR / "storage" / "artifacts"))
).resolve()
ARTIFACT_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

if ARTIFACT_STORAGE_BACKEND == "s3":
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
        "artifacts": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": env("AWS_STORAGE_BUCKET_NAME", default=""),
                "endpoint_url": env("AWS_S3_ENDPOINT_URL", default=None),
                "region_name": env("AWS_S3_REGION_NAME", default=None),
                "access_key": env("AWS_ACCESS_KEY_ID", default=None),
                "secret_key": env("AWS_SECRET_ACCESS_KEY", default=None),
                "default_acl": "private",
                "querystring_auth": True,
            },
        },
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
        "artifacts": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(ARTIFACT_STORAGE_ROOT)},
        },
    }

# ---------------------------------------------------------------------------
# Build orchestration paths (consumed by builds.tasks)
# ---------------------------------------------------------------------------

PACKER_BIN = env("PACKER_BIN", default="packer")
PACKER_TEMPLATES_ROOT = Path(env("PACKER_TEMPLATES_ROOT", default=str(BASE_DIR / "packer"))).resolve()
SALT_STATES_ROOT = Path(env("SALT_STATES_ROOT", default=str(BASE_DIR / "salt" / "states"))).resolve()
SALT_PILLAR_ROOT = Path(env("SALT_PILLAR_ROOT", default=str(BASE_DIR / "salt" / "pillar"))).resolve()
BUILD_WORK_ROOT = Path(env("BUILD_WORK_ROOT", default=str(BASE_DIR / "storage" / "work"))).resolve()
BUILD_WORK_ROOT.mkdir(parents=True, exist_ok=True)

DOWNLOAD_TOKEN_TTL_HOURS = env.int("DOWNLOAD_TOKEN_TTL_HOURS", default=72)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} :: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "osbakery": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "builds": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}
