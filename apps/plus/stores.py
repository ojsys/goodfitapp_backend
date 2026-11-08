"""Talking to the App Store and Google Play.

Apple: the app sends the StoreKit 2 signed transaction (a JWS). Its
certificate chain must end at Apple Root CA - G3 (bundled in certs/), the
intermediate and leaf must carry Apple's marker extensions, and the
signature must check out with the leaf's key. App Store Server Notifications
(V2) are signed the same way.

Google: the app sends the purchase token; we ask the Play Developer API
(subscriptionsv2) what it is, with the service account in
GOOGLE_PLAY_CREDENTIALS_JSON (or a path in GOOGLE_PLAY_CREDENTIALS).
"""

import base64
import json
import os
from datetime import datetime, timezone as dt_tz

import jwt
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from django.conf import settings

CERTS = os.path.join(os.path.dirname(__file__), 'certs')
# Apple's marker extensions (Apple PKI): leaf "Mac App Store receipt
# signing" and the WWDR intermediate.
APPLE_LEAF_OID = x509.ObjectIdentifier('1.2.840.113635.100.6.11.1')
APPLE_INTERMEDIATE_OID = x509.ObjectIdentifier('1.2.840.113635.100.6.2.1')


class StoreError(Exception):
    def __init__(self, code, message, http=400):
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


# ------------------------------------------------------------------ Apple

def apple_roots():
    """Trusted roots (tests swap in their own)."""
    paths = getattr(settings, 'APPLE_ROOT_CERTS', None) or [os.path.join(CERTS, 'AppleRootCA-G3.cer')]
    out = []
    for p in paths:
        with open(p, 'rb') as f:
            data = f.read()
        try:
            out.append(x509.load_der_x509_certificate(data))
        except ValueError:
            out.append(x509.load_pem_x509_certificate(data))
    return out


def _has(cert, oid):
    try:
        cert.extensions.get_extension_for_oid(oid)
        return True
    except x509.ExtensionNotFound:
        return False


def verify_apple_jws(token):
    """The payload of an Apple-signed JWS, or StoreError."""
    if not isinstance(token, str) or token.count('.') != 2:
        raise StoreError('invalid', 'That isn’t an App Store purchase.')
    try:
        header = jwt.get_unverified_header(token)
        chain = [x509.load_der_x509_certificate(base64.b64decode(c)) for c in header.get('x5c') or []]
    except Exception:
        raise StoreError('invalid', 'That isn’t an App Store purchase.')
    if header.get('alg') != 'ES256' or len(chain) < 3:
        raise StoreError('invalid', 'That isn’t an App Store purchase.')
    roots = {r.fingerprint(hashes.SHA256()) for r in apple_roots()}
    if chain[-1].fingerprint(hashes.SHA256()) not in roots:
        raise StoreError('untrusted', 'That purchase wasn’t signed by Apple.')
    now = datetime.now(dt_tz.utc)
    try:
        for cert, issuer in zip(chain, chain[1:]):
            cert.verify_directly_issued_by(issuer)
        for cert in chain:
            if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
                raise ValueError('expired certificate')
    except Exception:
        raise StoreError('untrusted', 'That purchase wasn’t signed by Apple.')
    if not _has(chain[0], APPLE_LEAF_OID) or not _has(chain[1], APPLE_INTERMEDIATE_OID):
        raise StoreError('untrusted', 'That purchase wasn’t signed by Apple.')
    try:
        return jwt.decode(token, key=chain[0].public_key(), algorithms=['ES256'],
                          options={'verify_aud': False, 'verify_exp': False})
    except jwt.PyJWTError:
        raise StoreError('untrusted', 'That purchase wasn’t signed by Apple.')


def check_bundle(bundle_id):
    want = settings.APPLE_BUNDLE_ID
    if want and bundle_id and bundle_id != want:
        raise StoreError('wrong_app', 'That purchase is for a different app.')


# ----------------------------------------------------------------- Google

_PLAY = 'https://androidpublisher.googleapis.com/androidpublisher/v3/applications'


def google_configured():
    return bool(settings.GOOGLE_PLAY_PACKAGE and (settings.GOOGLE_PLAY_CREDENTIALS_JSON
                                                   or settings.GOOGLE_PLAY_CREDENTIALS))


def _google_token():
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    info = settings.GOOGLE_PLAY_CREDENTIALS_JSON
    scopes = ['https://www.googleapis.com/auth/androidpublisher']
    if info:
        creds = service_account.Credentials.from_service_account_info(json.loads(info), scopes=scopes)
    else:
        creds = service_account.Credentials.from_service_account_file(settings.GOOGLE_PLAY_CREDENTIALS,
                                                                      scopes=scopes)
    creds.refresh(Request())
    return creds.token


def google_subscription(purchase_token):
    """subscriptionsv2.get for this purchase token."""
    if not google_configured():
        raise StoreError('store_unavailable', 'Google Play purchases aren’t set up yet.', 503)
    if not isinstance(purchase_token, str) or not purchase_token or len(purchase_token) > 400:
        raise StoreError('invalid', 'That isn’t a Google Play purchase.')
    try:
        r = requests.get(f'{_PLAY}/{settings.GOOGLE_PLAY_PACKAGE}/purchases/subscriptionsv2/tokens/{purchase_token}',
                         headers={'Authorization': f'Bearer {_google_token()}'}, timeout=15)
    except Exception:
        raise StoreError('store_down', 'Couldn’t reach Google Play. Try again.', 502)
    if r.status_code in (400, 404, 410):
        raise StoreError('invalid', 'Google Play doesn’t know that purchase.')
    if r.status_code != 200:
        raise StoreError('store_down', 'Couldn’t reach Google Play. Try again.', 502)
    return r.json()
