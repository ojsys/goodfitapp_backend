#!/usr/bin/env python
"""
Show how the current .env actually resolves, without printing secrets.

Run from the application root, inside the app's virtualenv:

    python check_env.py

Useful when a value looks right in the file but Django disagrees — a stray
quote, a trailing space or a line break puts a value in the wrong key, and
that is invisible by eye.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BASE_DIR, '.env'), override=False)
except ImportError:
    print('note: python-dotenv not installed; reading process environment only')

from decouple import config  # noqa: E402


def show(key, *, secret=False, default='<MISSING>'):
    value = config(key, default=default)
    text = str(value)

    if secret and text != default:
        shown = f'{text[:2]}…{text[-2:]} ({len(text)} chars)' if len(text) > 4 else '****'
    else:
        shown = repr(text)

    flags = []
    if text != default:
        if text != text.strip():
            flags.append('HAS SURROUNDING WHITESPACE')
        if text.startswith(('"', "'")) or text.endswith(('"', "'")):
            flags.append('HAS QUOTE CHARACTERS — remove them')
        if '\n' in text or '\r' in text:
            flags.append('CONTAINS A LINE BREAK')

    suffix = ('  <-- ' + '; '.join(flags)) if flags else ''
    print(f'  {key:<22} {shown}{suffix}')


print('\nDjango')
show('DJANGO_SETTINGS_MODULE', default='goodfit_api.settings.cpanel')
show('SECRET_KEY', secret=True)
show('ALLOWED_HOSTS')
show('CSRF_TRUSTED_ORIGINS', default='')

print('\nDatabase')
show('DATABASE_URL', secret=True, default='<not set — using DB_* fields>')
show('DB_NAME')
show('DB_USER')
show('DB_PASSWORD', secret=True)
show('DB_HOST', default='localhost')
show('DB_PORT', default='5432')

port = str(config('DB_PORT', default='5432')).strip()
if not port.isdigit():
    print(f"\n  ERROR: DB_PORT is {port!r}, which is not a number.")
    print("  A value has been pasted into the wrong key in .env.")

print('\nPaths')
show('STATIC_ROOT', default='<default>')
show('MEDIA_ROOT', default='<default>')

print('\nConnecting to PostgreSQL…')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'goodfit_api.settings.cpanel')
try:
    import django

    django.setup()
    from django.db import connection

    connection.ensure_connection()
    print('  OK — connected and authenticated.\n')
except Exception as exc:  # noqa: BLE001 — this script exists to report anything
    print(f'  FAILED: {type(exc).__name__}: {exc}\n')
