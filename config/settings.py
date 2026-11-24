"""Налаштування проєкту «Тусовка». Усі секрети та залежні від середовища значення — зі змінних середовища."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    USE_X_FORWARDED_FOR=(bool, False),
    SECURE_SSL_REDIRECT=(bool, False),
    SECURE_HSTS_SECONDS=(int, 0),
    LOG_LEVEL=(str, "INFO"),
)
# Локально читаємо .env, якщо він є. У проді змінні задає платформа.
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

DEBUG = env("DEBUG")


def _local_secret_key():
    """Якщо SECRET_KEY не задано (напр. запуск з чистого клону без .env) — генеруємо ключ один раз
    і зберігаємо у .secret_key (у .gitignore), щоб усі процеси/воркери мали той самий ключ.
    У проді SECRET_KEY має задаватися змінною середовища."""
    import logging
    import secrets

    path = BASE_DIR / ".secret_key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(50))
        path.chmod(0o600)
        logging.getLogger(__name__).warning("SECRET_KEY не задано: згенеровано локальний ключ у %s", path)
    return path.read_text().strip()


SECRET_KEY = env("SECRET_KEY", default="") or _local_secret_key()

# Без явного ALLOWED_HOSTS: у DEBUG — будь-який хост (локальна розробка, контейнери),
# у проді — лише локальні адреси (для публічного домену задайте ALLOWED_HOSTS).
ALLOWED_HOSTS = env("ALLOWED_HOSTS") or (
    ["*"] if DEBUG else ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]
)
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "accounts",
    "events",
]

MIDDLEWARE = [
    "config.middleware.RequestSizeLimitMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db(
        "DATABASE_URL", default="postgres://tusovka:tusovka@localhost:5432/tusovka"
    )
}
DATABASES["default"]["CONN_MAX_AGE"] = 60
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

# Кеш у БД: спільний для всіх воркерів gunicorn (потрібен для rate limit).
# Таблиця створюється міграцією accounts/0002.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "tusovka_cache",
    }
}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "events:home"
LOGOUT_REDIRECT_URL = "events:home"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "uk"
TIME_ZONE = "Europe/Kyiv"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Медіа НЕ роздаються як статика: обкладинки віддає view з перевіркою доступу.
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media"))).resolve()
MEDIA_URL = "/media-not-served/"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "config.storage.ForgivingManifestStaticFilesStorage"},
}
# Віддавати статику і без collectstatic (напр. `runserver` з DEBUG=False одразу після клону).
WHITENOISE_USE_FINDERS = True

# Обмеження розміру запитів/завантажень.
COVER_MAX_BYTES = 5 * 1024 * 1024
COVER_MAX_DIMENSION = 6000
FILE_UPLOAD_MAX_MEMORY_SIZE = COVER_MAX_BYTES
DATA_UPLOAD_MAX_MEMORY_SIZE = COVER_MAX_BYTES
REQUEST_BODY_MAX_BYTES = COVER_MAX_BYTES + 512 * 1024  # файл + поля форми

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Безпека ---
SESSION_COOKIE_HTTPONLY = True
# Secure-cookie поза DEBUG (вимога ТЗ). SECURE_COOKIES=False — лише для локальної перевірки по HTTP.
SECURE_COOKIES = env.bool("SECURE_COOKIES", default=not DEBUG)
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_HTTPONLY = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT")
SECURE_HSTS_SECONDS = env("SECURE_HSTS_SECONDS")
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# Брати IP клієнта з X-Forwarded-For (лише за довіреним проксі, напр. Railway).
USE_X_FORWARDED_FOR = env("USE_X_FORWARDED_FOR")

# --- Rate limits ---
LOGIN_RATE_LIMIT = (5, 15 * 60)  # 5 невдалих спроб / 15 хв на email+IP
SIGNUP_RATE_LIMIT = (5, 60 * 60)  # 5 реєстрацій / година на IP
COMMENT_RATE_LIMIT_SECONDS = 5  # не частіше 1 коментаря на 5 с

# --- Логування у stdout ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
