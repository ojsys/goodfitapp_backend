"""
WSGI config for GoodFit API.
"""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'goodfit_api.settings')

application = get_wsgi_application()
