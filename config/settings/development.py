import secrets

from .base import *

DEBUG = env_bool("DJANGO_DEBUG", True)
# Ephemeral development key only. Set a persistent random key in local .env.
SECRET_KEY = SECRET_KEY or secrets.token_urlsafe(64)
ALLOW_DEMO_DATA = DEBUG and env_bool("ALLOW_DEMO_DATA")
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
