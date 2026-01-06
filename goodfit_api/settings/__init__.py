"""
Settings package for GoodFit API

Automatically loads the appropriate settings based on DJANGO_ENV environment variable:
- development (default)
- production

Usage:
    export DJANGO_ENV=production
    python manage.py runserver
"""

import os

# Get environment from DJANGO_ENV variable (defaults to development)
ENVIRONMENT = os.environ.get('DJANGO_ENV', 'development')

if ENVIRONMENT == 'production':
    from .production import *
    print("✅ Loaded PRODUCTION settings")
elif ENVIRONMENT == 'development':
    from .development import *
    print("✅ Loaded DEVELOPMENT settings")
else:
    raise ValueError(
        f"Unknown DJANGO_ENV: {ENVIRONMENT}. "
        "Must be either 'development' or 'production'"
    )