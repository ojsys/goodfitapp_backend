"""
Verify Sign in with Apple and Google ID tokens.

Both return a SocialIdentity. Tokens are checked for signature, issuer and
audience: the audience must be one of OUR client IDs (settings
APPLE_CLIENT_IDS / GOOGLE_CLIENT_IDS), otherwise a token minted for any other
app would sign someone in here.
"""

from dataclasses import dataclass

import jwt
from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

APPLE_ISSUER = 'https://appleid.apple.com'
APPLE_KEYS_URL = 'https://appleid.apple.com/auth/keys'

_apple_jwks = None


class SocialAuthError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class SocialIdentity:
    provider: str  # 'apple' | 'google'
    subject: str
    email: str | None
    email_verified: bool
    first_name: str = ''
    last_name: str = ''
    picture: str | None = None


def verify_apple(identity_token):
    if not settings.APPLE_CLIENT_IDS:
        raise SocialAuthError('not_configured', 'Sign in with Apple is not set up yet.')
    global _apple_jwks
    if _apple_jwks is None:
        _apple_jwks = jwt.PyJWKClient(APPLE_KEYS_URL, cache_keys=True)
    try:
        key = _apple_jwks.get_signing_key_from_jwt(identity_token)
        claims = jwt.decode(
            identity_token,
            key.key,
            algorithms=['RS256'],
            audience=settings.APPLE_CLIENT_IDS,
            issuer=APPLE_ISSUER,
        )
    except jwt.PyJWTError as exc:
        raise SocialAuthError('invalid_token', f'Apple sign-in failed: {exc}')
    verified = claims.get('email_verified') in (True, 'true')
    return SocialIdentity(
        provider='apple',
        subject=claims['sub'],
        email=claims.get('email'),
        email_verified=verified,
    )


def verify_google(token):
    if not settings.GOOGLE_CLIENT_IDS:
        raise SocialAuthError('not_configured', 'Google sign-in is not set up yet.')
    try:
        claims = google_id_token.verify_oauth2_token(token, google_requests.Request())
    except ValueError as exc:
        raise SocialAuthError('invalid_token', f'Google sign-in failed: {exc}')
    if claims.get('aud') not in settings.GOOGLE_CLIENT_IDS:
        raise SocialAuthError('invalid_token', 'Google sign-in failed: wrong audience.')
    return SocialIdentity(
        provider='google',
        subject=claims['sub'],
        email=claims.get('email'),
        email_verified=bool(claims.get('email_verified')),
        first_name=claims.get('given_name', ''),
        last_name=claims.get('family_name', ''),
        picture=claims.get('picture'),
    )
