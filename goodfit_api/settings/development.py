"""
Development settings for GoodFit API
Use this for local development
"""

from .base import *
from decouple import config

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Allow all hosts in development
ALLOWED_HOSTS = ['*']

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='goodfit_dev_db'),
        'USER': config('DB_USER', default='Apple'),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# CORS Settings for Development
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",      # React development
    "http://localhost:19000",     # Expo development
    "http://localhost:19001",
    "http://localhost:19002",
    "http://localhost:8081",      # React Native Metro
    "http://127.0.0.1:8081",
    "http://192.168.1.*",         # Local network
]

# Allow all origins in development (can be restrictive if needed)
CORS_ALLOW_ALL_ORIGINS = True

# Development-specific apps (optional - uncomment if needed)
# INSTALLED_APPS += [
#     'django_debug_toolbar',
# ]

# Development middleware (optional - uncomment if needed)
# MIDDLEWARE += [
#     'django_debug_toolbar.middleware.DebugToolbarMiddleware',
# ]

# Django Debug Toolbar settings (optional - uncomment if needed)
# INTERNAL_IPS = [
#     '127.0.0.1',
#     'localhost',
# ]

# Email backend for development (console)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Logging configuration for development
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

# Add browsable API renderer in development
REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = [
    'rest_framework.renderers.JSONRenderer',
    'rest_framework.renderers.BrowsableAPIRenderer',
]

# Cache (use local memory cache for development)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'goodfit-dev-cache',
    }
}

# Disable some security features for easier development
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

print("🔧 Running in DEVELOPMENT mode")
print(f"📊 Database: {DATABASES['default']['NAME']}")
print(f"🌐 CORS: Allow all origins = {CORS_ALLOW_ALL_ORIGINS}")
