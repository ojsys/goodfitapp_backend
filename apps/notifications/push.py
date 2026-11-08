"""
Push through Firebase Cloud Messaging (HTTP v1), which reaches both iPhone
(via your APNs key uploaded to Firebase) and Android.

Off until configured. Set in the server's .env:
    FCM_PROJECT_ID=your-firebase-project-id
    FCM_CREDENTIALS=/app/secrets/firebase.json   (service account key file)
or FCM_CREDENTIALS_JSON with the key file's contents.

Sending happens on a background thread after the database commit, so a slow
or failing push never slows down or breaks the request that caused it.
"""

import json
import logging
import threading

from django.conf import settings
from django.db import transaction

log = logging.getLogger('apps.notifications')
_lock = threading.Lock()
_creds = None


def enabled():
    return bool(getattr(settings, 'FCM_PROJECT_ID', '') and (
        getattr(settings, 'FCM_CREDENTIALS', '') or getattr(settings, 'FCM_CREDENTIALS_JSON', '')))


def _token():
    global _creds
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    with _lock:
        if _creds is None:
            scopes = ['https://www.googleapis.com/auth/firebase.messaging']
            raw = getattr(settings, 'FCM_CREDENTIALS_JSON', '')
            _creds = (service_account.Credentials.from_service_account_info(json.loads(raw), scopes=scopes) if raw
                      else service_account.Credentials.from_service_account_file(settings.FCM_CREDENTIALS, scopes=scopes))
        if not _creds.valid:
            _creds.refresh(Request())
        return _creds.token


def _send_now(tokens, title, body, data):
    import requests
    from .models import Device
    url = f'https://fcm.googleapis.com/v1/projects/{settings.FCM_PROJECT_ID}/messages:send'
    try:
        auth = {'Authorization': f'Bearer {_token()}'}
    except Exception:
        log.exception('push: could not get a Firebase token')
        return
    for t in tokens:
        msg = {'message': {
            'token': t,
            'notification': {'title': title, 'body': body},
            'data': {k: str(v) for k, v in (data or {}).items()},
            'apns': {'payload': {'aps': {'sound': 'default'}}},
            'android': {'priority': 'high'},
        }}
        try:
            r = requests.post(url, json=msg, headers=auth, timeout=8)
        except requests.RequestException:
            log.warning('push: network error')
            continue
        if r.status_code in (400, 404) and ('UNREGISTERED' in r.text or 'INVALID_ARGUMENT' in r.text):
            Device.objects.filter(token=t).delete()  # app uninstalled or token rotated
        elif r.status_code >= 300:
            log.warning('push: %s %s', r.status_code, r.text[:200])


def send(user, title, body, data=None):
    """Queue a push to all of `user`'s phones (no-op when push is off)."""
    if not enabled():
        return
    tokens = list(user.devices.values_list('token', flat=True))
    if not tokens:
        return
    transaction.on_commit(lambda: threading.Thread(
        target=_send_now, args=(tokens, title, body, data), daemon=True).start())
