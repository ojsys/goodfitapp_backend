"""
Phusion Passenger entry point for cPanel.

cPanel's "Setup Python App" looks for this file in the application root and
imports `application` from it. There is no gunicorn and no Procfile here —
Passenger owns the process.

To apply code changes after an upload, restart the app from cPanel or run:

    touch tmp/restart.txt
"""

import os
import sys

# The project root is this file's directory; make sure it is importable no
# matter which working directory Passenger starts us in.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Passenger starts the process with an ASCII stdout (no locale is set), so any
# non-ASCII character written to a log — an emoji in a startup banner, an
# accented name in a traceback, a message body — raises UnicodeEncodeError and
# takes down the worker. Force UTF-8 and replace anything unencodable rather
# than letting logging kill the app.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        # Older Python, or a stream that does not support reconfiguration.
        pass

# Load environment variables from a .env file sitting next to this script.
# cPanel can set variables through its UI too, and those win: only keys that
# are not already present are filled in.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BASE_DIR, '.env'), override=False)
except ImportError:
    # python-dotenv missing is not fatal — cPanel-provided variables still work.
    pass

# Default to the cPanel settings module, while still allowing an override from
# the environment (handy for running management commands with other settings).
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'goodfit_api.settings.cpanel')

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
