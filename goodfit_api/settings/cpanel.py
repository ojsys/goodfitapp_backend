"""
cPanel / Phusion Passenger settings for GoodFit API.

Shared cPanel hosting differs from a container platform in ways that matter:

* Passenger runs the app, not gunicorn -- see `passenger_wsgi.py`.
* Apache sits in front, terminating TLS, so Django sees plain HTTP.
* Static and media files are served by Apache straight off disk, which is
  faster than routing them through Python.
* There is usually no Redis and no long-running worker process.

Activate with:  DJANGO_SETTINGS_MODULE=goodfit_api.settings.cpanel
"""

from .production import *  # noqa: F401,F403
from decouple import config

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# On cPanel the document root is typically ~/public_html (or a subdomain
# folder). Point collectstatic and uploads there so Apache can serve them
# without touching Python. Both default to project-local folders, which keeps
# the settings importable during a local check.
STATIC_ROOT = config('STATIC_ROOT', default=os.path.join(BASE_DIR, 'staticfiles'))  # noqa: F405
MEDIA_ROOT = config('MEDIA_ROOT', default=os.path.join(BASE_DIR, 'media'))  # noqa: F405

STATIC_URL = config('STATIC_URL', default='/static/')
MEDIA_URL = config('MEDIA_URL', default='/media/')

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
# WhiteNoise still runs so the admin keeps working if Apache is not configured
# to serve /static/ yet, but the plain storage backend is used: the manifest
# variant raises at runtime for any file missing from the manifest, which is a
# harsh failure mode on a host where you cannot watch the logs easily.
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}

# ---------------------------------------------------------------------------
# HTTPS
# ---------------------------------------------------------------------------
# Most cPanel accounts already force HTTPS at the Apache level (AutoSSL plus a
# redirect rule). Doing it twice is what produces redirect loops, so this
# defaults to off here and can be switched on if Apache is not doing it.
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=False, cast=bool)

# Passenger passes the original scheme through this header.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Shared hosting has no journal to read, so keep file logging (inherited from
# production) but drop the mail_admins handler unless SMTP is actually
# configured -- an unreachable mail server turns every error into two errors.
if not config('EMAIL_HOST_USER', default=''):
    LOGGING['loggers']['django.request']['handlers'] = ['file']  # noqa: F405

# No startup printing here either -- see the note in production.py.
