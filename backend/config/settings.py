"""
Django settings for BetterSharedEditor project.
"""

import os
from pathlib import Path

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-dev-key-change-in-production-!@#$%^&*()")

DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "core.middleware.RequestTimingMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "config.wsgi.application"

# Tarantool configuration
# Prefer the explicit Compose container hostname to avoid Docker DNS ambiguity.
TARANTOOL_HOST = os.environ.get("TARANTOOL_HOST", "tarantool")
TARANTOOL_PORT = int(os.environ.get("TARANTOOL_PORT", "3301"))
TARANTOOL_USER = os.environ.get("TARANTOOL_USER", "admin")
TARANTOOL_PASSWORD = os.environ.get("TARANTOOL_PASSWORD", "password")
TARANTOOL_CONN_MAX_AGE = int(os.environ.get("TARANTOOL_CONN_MAX_AGE", "3600"))

# Database — SQLite for Django internals, Tarantool for room metadata via Django ORM
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    },
    "tarantool": {
        "ENGINE": "django_tarantool.backend",
        "HOST": TARANTOOL_HOST,
        "PORT": TARANTOOL_PORT,
        "USER": TARANTOOL_USER,
        "PASSWORD": TARANTOOL_PASSWORD,
        "CONN_MAX_AGE": TARANTOOL_CONN_MAX_AGE,
        "OPTIONS": {},
    },
}

DATABASE_ROUTERS = ["core.db_routers.TarantoolRouter"]

# Centrifugo configuration
CENTRIFUGO_API_URL = os.environ.get("CENTRIFUGO_API_URL", "http://localhost:8001")
CENTRIFUGO_API_KEY = os.environ.get("CENTRIFUGO_API_KEY", "secret-api-key")
CENTRIFUGO_HMAC_KEY = os.environ.get("CENTRIFUGO_HMAC_KEY", "secret-hmac-key")

# Redis hot cache for current room state
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
REDIS_ROOM_STATE_TTL_SECONDS = int(
    os.environ.get("REDIS_ROOM_STATE_TTL_SECONDS", "900")  # 15 минут
)

AWS_S3_ENDPOINT_URL = os.environ.get("AWS_S3_ENDPOINT_URL", "http://minio:9000")
AWS_S3_ACCESS_KEY = os.environ.get("AWS_S3_ACCESS_KEY", "minioadmin")
AWS_S3_SECRET_KEY = os.environ.get("AWS_S3_SECRET_KEY", "minioadmin")
AWS_S3_BUCKET_NAME = os.environ.get("AWS_S3_BUCKET_NAME", "bse")

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Default primary key
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "core": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}
