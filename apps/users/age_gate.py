"""
The 21+ age gate.

Rules (Technical Requirements, "Accounts, sign-up and the 21+ age gate"):

- Age is computed on the server from the birthday against the current date in
  the member's time zone. Under 21 means no account is created.
- Apple / Google sign-ins are held as pending sign-ups until the birthday
  passes. When one fails, a flag is stored for that sign-in ID (never the
  birthday) and retries from it are blocked.
- The birthday of someone who failed is never kept.
- Birthdays are stored encrypted; only the computed age is ever exposed to
  others, and only inside A Good Match.
"""

import base64
import datetime as dt
import hashlib
import hmac
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

MINIMUM_AGE = 21


class AgeGateError(Exception):
    """Raised when a birthday is invalid or under the minimum age."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# --- Time zone and age -------------------------------------------------------

def safe_zone(name):
    """The member's IANA time zone, falling back to UTC for unknown names."""
    try:
        return ZoneInfo(name or 'UTC')
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo('UTC')


def today_in(tz_name, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    return now.astimezone(safe_zone(tz_name)).date()


def compute_age(birthday, tz_name='UTC', now=None):
    today = today_in(tz_name, now)
    before_birthday = (today.month, today.day) < (birthday.month, birthday.day)
    return today.year - birthday.year - (1 if before_birthday else 0)


def parse_birthday(year, month, day, tz_name='UTC', now=None):
    """Validate a birthday and enforce the gate. Returns a date."""
    try:
        birthday = dt.date(int(year), int(month), int(day))
    except (TypeError, ValueError):
        raise AgeGateError('invalid_birthday', 'Enter a real date.')
    if birthday > today_in(tz_name, now) or birthday.year < 1900:
        raise AgeGateError('invalid_birthday', 'Enter a real date.')
    if compute_age(birthday, tz_name, now) < MINIMUM_AGE:
        raise AgeGateError(
            'under_21', 'You must be 21 or older to join A Good Fit.'
        )
    return birthday


# --- Encryption --------------------------------------------------------------

def _fernet():
    key = getattr(settings, 'BIRTHDAY_ENCRYPTION_KEY', '') or ''
    if not key:
        # Derive a stable key from SECRET_KEY so development works without
        # extra setup. Production must set BIRTHDAY_ENCRYPTION_KEY (see
        # settings) so rotating SECRET_KEY never loses birthdays.
        digest = hashlib.sha256(('birthday:' + settings.SECRET_KEY).encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_birthday(birthday):
    return _fernet().encrypt(birthday.isoformat().encode()).decode()


def decrypt_birthday(token):
    if not token:
        return None
    try:
        return dt.date.fromisoformat(_fernet().decrypt(token.encode()).decode())
    except (InvalidToken, ValueError):
        return None


# --- Sign-in ID flags ----------------------------------------------------------

def subject_hash(provider, subject):
    """A keyed hash of an Apple/Google user ID, so the block list never holds
    the raw identifier."""
    msg = f'{provider}:{subject}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()
