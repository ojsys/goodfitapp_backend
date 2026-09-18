"""
Production settings for GoodFit API
Use this for production deployment
"""

from .base import *
from decouple import config
import dj_database_url

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

# Only allow specific hosts in production
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='*').split(',')

# Ensure SECRET_KEY is set in production
SECRET_KEY = config('SECRET_KEY')
if SECRET_KEY == 'django-insecure-change-this-in-production':
    raise ValueError("SECRET_KEY must be set in production!")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# DATABASE_URL wins when set. Otherwise the connection is built from the
# individual DB_* settings as a plain dict.
#
# It is deliberately NOT assembled into a URL string: a password containing
# any of @ : / # % — which cPanel-generated passwords routinely do — corrupts
# the URL and surfaces as a baffling parse error somewhere else in the string,
# such as the password being read as the port. Passing the fields straight
# through to the driver needs no escaping and cannot be mis-split.
DATABASE_URL = config('DATABASE_URL', default='')

if DATABASE_URL:
    DATABASES = {'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
else:
    DB_PORT = config('DB_PORT', default='5432')

    # A non-numeric port almost always means a .env line is in the wrong slot,
    # so say that plainly instead of failing later inside a URL parser.
    if not str(DB_PORT).strip().isdigit():
        raise ValueError(
            f"DB_PORT must be a number, got {DB_PORT!r}. "
            "Check that DB_PORT, DB_PASSWORD and DB_HOST are on their own "
            "lines in .env and none of the values have been pasted into the "
            "wrong key."
        )

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME'),
            'USER': config('DB_USER'),
            'PASSWORD': config('DB_PASSWORD'),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': str(DB_PORT).strip(),
            # Reuse connections instead of reconnecting on every request;
            # shared hosts are slow to open new ones.
            'CONN_MAX_AGE': 600,
        }
    }

# CORS Settings for Production
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='https://yourdomain.com,https://www.yourdomain.com'
).split(',')

# Never allow all origins in production
CORS_ALLOW_ALL_ORIGINS = False

# Security Settings
#
# Behind Apache/Passenger the request reaches Django over plain HTTP, so
# without this header Django believes every request is insecure and
# SECURE_SSL_REDIRECT redirects forever. Disable the redirect only if the
# web server already handles it.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
X_FRAME_OPTIONS = 'DENY'

# CSRF Settings
# Django 4+ requires the scheme, e.g. https://api.example.com
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in config('CSRF_TRUSTED_ORIGINS', default='').split(',')
    if origin.strip()
]

CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_SAMESITE = 'Strict'

# Password hashers.
#
# Argon2 is preferred, but it needs the `argon2-cffi` package — and if that is
# missing, Django raises on every login and signup. Shared hosts do not always
# have it, so it is only put first when it can actually be imported.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
]

try:
    import argon2  # noqa: F401
    PASSWORD_HASHERS.insert(0, 'django.contrib.auth.hashers.Argon2PasswordHasher')
except ImportError:
    pass

# Email backend for production
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@goodfit.com')

# Logging configuration for production
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'level': 'ERROR',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'django_errors.log'),
            'formatter': 'verbose',
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
            'filters': ['require_debug_false'],
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['mail_admins', 'file'],
            'level': 'ERROR',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Create logs directory if it doesn't exist
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

# Only use JSON renderer in production (no browsable API)
REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = [
    'rest_framework.renderers.JSONRenderer',
]

# Cache.
#
# Redis is used when REDIS_URL is set and the client library is installed.
# Otherwise fall back to per-process local memory, which is correct (if not
# shared between workers) and never fails at runtime the way a missing Redis
# does.
REDIS_URL = config('REDIS_URL', default='')

if REDIS_URL:
    try:
        import redis  # noqa: F401
        CACHES = {
            'default': {
                'BACKEND': 'django.core.cache.backends.redis.RedisCache',
                'LOCATION': REDIS_URL,
            }
        }
    except ImportError:
        REDIS_URL = ''

if not REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'goodfit-cache',
        }
    }

# Admin configuration
ADMINS = [
    ('Admin', config('ADMIN_EMAIL', default='admin@goodfit.com')),
]

MANAGERS = ADMINS

# Static files - using WhiteNoise for Render
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATIC_URL = '/static/'

# Media files (consider using AWS S3 or similar)
# AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID', default='')
# AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY', default='')
# AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME', default='')
# DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

print("🚀 Running in PRODUCTION mode")
print(f"🔒 DEBUG = {DEBUG}")
print(f"🌐 Allowed hosts: {ALLOWED_HOSTS}")
