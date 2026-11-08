"""
Base Django settings for GoodFit API
Common settings shared across all environments
"""

import os
from pathlib import Path
from datetime import timedelta
from decouple import config

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Security settings (override in production)
SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-this-in-production')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party apps
    'rest_framework',
    'rest_framework.authtoken',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'drf_yasg',

    # Local apps
    'apps.users',
    'apps.activities',
    'apps.events',
    'apps.matching',
    'apps.messaging',
    'apps.social',
    'apps.routes',
    'apps.chats',
    'apps.safety',
    'apps.notifications',
    'apps.performance',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',  # CORS must be before CommonMiddleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'goodfit_api.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'goodfit_api.wsgi.application'

# Custom User Model
AUTH_USER_MODEL = 'users.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Media files
MEDIA_URL = 'media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework Configuration
REST_FRAMEWORK = {
    # MemberJWTAuthentication refuses accounts that haven't finished sign-up
    # (age gate, guidelines) everywhere except onboarding views.
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'apps.users.authentication.MemberJWTAuthentication',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'auth': '30/hour',
        'password_reset': '5/hour',
        # Requirements: rate-limit messaging and reports.
        'messages': '120/hour',
        'reports': '20/hour',
        'export': '5/day',
    },
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DATETIME_FORMAT': '%Y-%m-%dT%H:%M:%S.%fZ',
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

# JWT Settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=7),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'JTI_CLAIM': 'jti',
    'TOKEN_TYPE_CLAIM': 'token_type',
}

# CORS Settings (will be overridden in specific environments)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]


# --- A Good Fit accounts -------------------------------------------------------

# Bumped when the Community Guidelines change; agreements store this version.
GUIDELINES_VERSION = '2026-10-29'

# Fernet key for birthdays (generate: python -c "from cryptography.fernet import
# Fernet; print(Fernet.generate_key().decode())"). Required in production;
# development derives one from SECRET_KEY.
BIRTHDAY_ENCRYPTION_KEY = config('BIRTHDAY_ENCRYPTION_KEY', default='')

# Sign in with Apple: the app's bundle ID (and Services ID if web is added).
APPLE_CLIENT_IDS = [c for c in config('APPLE_CLIENT_IDS', default='').split(',') if c]
# Google OAuth client IDs whose ID tokens we accept (iOS, Android, web).
GOOGLE_CLIENT_IDS = [c for c in config('GOOGLE_CLIENT_IDS', default='').split(',') if c]

# Public base URL used in password reset emails.
PUBLIC_BASE_URL = config('PUBLIC_BASE_URL', default='http://localhost:8000')

# Create a route (Phase 3): road snapping and elevation. Empty = straight
# lines and no climb. See apps/routes/services.py.
ROUTING_URL_BIKE = config('ROUTING_URL_BIKE', default='')
ROUTING_URL_FOOT = config('ROUTING_URL_FOOT', default='')
ELEVATION_URL = config('ELEVATION_URL', default='')
# Free members can keep this many routes; Plus is unlimited (requirements: Plans).
FREE_ROUTE_LIMIT = config('FREE_ROUTE_LIMIT', default=5, cast=int)


# --- API docs (/docs/, /redoc/, /openapi.json) ---------------------------------
SWAGGER_SETTINGS = {
    'DEFAULT_INFO': 'goodfit_api.api_docs.INFO',
    'DEFAULT_AUTO_SCHEMA_CLASS': 'goodfit_api.api_docs.AgfAutoSchema',
    'DEFAULT_GENERATOR_CLASS': 'goodfit_api.api_docs.AgfSchemaGenerator',
    'USE_SESSION_AUTH': False,
    'SECURITY_DEFINITIONS': {
        'Bearer': {
            'type': 'apiKey', 'in': 'header', 'name': 'Authorization',
            'description': 'Paste: Bearer <access token from /api/auth/login/>',
        },
    },
    'PERSIST_AUTH': True,
    'REFETCH_SCHEMA_WITH_AUTH': False,
    'DOC_EXPANSION': 'none',
    'DEEP_LINKING': True,
    'DEFAULT_MODEL_RENDERING': 'example',
    'DEFAULT_MODEL_DEPTH': 2,
    'DISPLAY_OPERATION_ID': False,
    'OPERATIONS_SORTER': None,
    'TAGS_SORTER': None,
}
REDOC_SETTINGS = {'HIDE_HOSTNAME': False, 'EXPAND_RESPONSES': '200,201', 'PATH_IN_MIDDLE': True}

# Push (Firebase Cloud Messaging). Off until both are set; see apps/notifications/push.py.
FCM_PROJECT_ID = config('FCM_PROJECT_ID', default='')
FCM_CREDENTIALS = config('FCM_CREDENTIALS', default='')
FCM_CREDENTIALS_JSON = config('FCM_CREDENTIALS_JSON', default='')
# Base for share links and their public preview pages.
SHARE_BASE_URL = config('SHARE_BASE_URL', default='') or PUBLIC_BASE_URL
