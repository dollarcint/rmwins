import os
from pathlib import Path

import dj_database_url


BASE_DIR = Path(__file__).resolve().parent.parent
IS_RENDER = bool(os.environ.get("RENDER"))

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-local-development-only")
DEBUG = os.environ.get("DJANGO_DEBUG", "false" if IS_RENDER else "true").lower() == "true"

default_hosts = "localhost,127.0.0.1,api.alessarsolutions.in,.onrender.com"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", default_hosts).split(",")
    if host.strip()
]
render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if render_hostname and render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_hostname)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "surveys",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "surveyboard.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "surveyboard.wsgi.application"
ASGI_APPLICATION = "surveyboard.asgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

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
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

csrf_origins = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "https://api.alessarsolutions.in")
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in csrf_origins.split(",") if origin.strip()]
if IS_RENDER:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False

INNOVATEMR_SURVEY_URL = os.environ.get(
    "INNOVATEMR_SURVEY_URL",
    "https://supplier.innovatemr.net/api/v2/supply/getAllocatedSurveys",
)
INNOVATEMR_ACCESS_TOKEN = os.environ.get("INNOVATEMR_ACCESS_TOKEN", "")
INNOVATEMR_TARGETING_URL = os.environ.get(
    "INNOVATEMR_TARGETING_URL",
    "https://supplier.innovatemr.net/api/v2/supply/getSurveyTargeting",
)
VOQALL_SURVEY_URL = os.environ.get(
    "VOQALL_SURVEY_URL",
    "https://partner-api.voqall.com/api/v1/surveys",
)
VOQALL_LANGUAGES_URL = os.environ.get(
    "VOQALL_LANGUAGES_URL",
    "https://partner-api.voqall.com/api/v1/collection/languages",
)
VOQALL_ACCESS_KEY = os.environ.get("VOQALL_ACCESS_KEY", "")
VOQALL_SURVEY_QUALIFICATIONS_URL = os.environ.get(
    "VOQALL_SURVEY_QUALIFICATIONS_URL",
    "https://partner-api.voqall.com/api/v1/survey-qualifications",
)
VOQALL_QUALIFICATION_CATALOG_URL = os.environ.get(
    "VOQALL_QUALIFICATION_CATALOG_URL",
    "https://partner-api.voqall.com/api/v1/collection/qualifications",
)
VOQALL_QUALIFICATION_DETAIL_URL = os.environ.get(
    "VOQALL_QUALIFICATION_DETAIL_URL",
    "https://partner-api.voqall.com/api/v1/collection/languages/{language_id}/qualifications/{qualification_id}",
)
SURVEY_FEED_TIMEOUT = int(os.environ.get("SURVEY_FEED_TIMEOUT", "15"))
SURVEY_CACHE_SECONDS = int(os.environ.get("SURVEY_CACHE_SECONDS", "12"))
SURVEY_QUESTION_TIMEOUT = int(os.environ.get("SURVEY_QUESTION_TIMEOUT", "10"))
SURVEY_QUESTION_CACHE_SECONDS = int(os.environ.get("SURVEY_QUESTION_CACHE_SECONDS", "300"))

SURVEY_LAUNCH_MAX_AGE_SECONDS = int(os.environ.get("SURVEY_LAUNCH_MAX_AGE_SECONDS", "604800"))

SURVEY_TRACKED_FLOW_ENABLED = os.environ.get("SURVEY_TRACKED_FLOW_ENABLED", "false").strip().lower() == "true"
