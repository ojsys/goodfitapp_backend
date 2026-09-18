"""
Settings package for GoodFit API.

There are two ways to choose settings, and they must not fight each other:

1. Point DJANGO_SETTINGS_MODULE at a specific module -- the explicit form, and
   what cPanel/Passenger uses:

       DJANGO_SETTINGS_MODULE=goodfit_api.settings.cpanel

2. Point it at this package and pick with DJANGO_ENV -- the older shorthand:

       DJANGO_SETTINGS_MODULE=goodfit_api.settings
       DJANGO_ENV=production

Importing a submodule also imports this package first. Without the guard
below, form 1 would load `development` (the DJANGO_ENV default) and only then
the module actually asked for -- so development settings, including
CORS_ALLOW_ALL_ORIGINS, were briefly applied in production.
"""

import os

_REQUESTED = os.environ.get('DJANGO_SETTINGS_MODULE', '')

# When a specific submodule was requested, this package must stay inert and let
# Django import that module on its own.
if _REQUESTED in ('', 'goodfit_api.settings'):
    ENVIRONMENT = os.environ.get('DJANGO_ENV', 'development')

    if ENVIRONMENT == 'production':
        from .production import *  # noqa: F401,F403
        print("Loaded PRODUCTION settings")
    elif ENVIRONMENT == 'cpanel':
        from .cpanel import *  # noqa: F401,F403
        print("Loaded CPANEL settings")
    elif ENVIRONMENT == 'development':
        from .development import *  # noqa: F401,F403
        print("Loaded DEVELOPMENT settings")
    else:
        raise ValueError(
            f"Unknown DJANGO_ENV: {ENVIRONMENT}. "
            "Must be 'development', 'production' or 'cpanel'."
        )
