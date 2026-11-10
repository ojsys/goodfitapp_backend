"""Every model in the app, browsable and editable from the staff dashboard.

Driven by Django's own model registry and permissions, so a new model shows
up without any work here. What a person can do follows Django permissions:
admins (superusers) can do everything; staff get what their groups allow
(see migrations/0001: the "Staff" group can view everything and act on the
review queues).

Some fields are never shown (passwords, tokens, encrypted birthdays) and
private conversation text is only shown to admins.
"""

import datetime
import decimal
import re
import uuid

from django.apps import apps
from django.contrib import admin
from django.db import models

APPS = ['users', 'activities', 'events', 'social', 'routes', 'chats', 'messaging', 'matching', 'goodmatch',
        'performance', 'safety', 'notifications', 'plus', 'business', 'auth']
APP_LABELS = {
    'users': 'Members', 'activities': 'Activities', 'events': 'Events', 'social': 'Community & clubs',
    'routes': 'Routes', 'chats': 'Chats', 'messaging': 'Messages (legacy)', 'matching': 'Matching (legacy)',
    'goodmatch': 'Fit Buddies', 'performance': 'Segments & challenges', 'safety': 'Trust & safety',
    'notifications': 'Notifications', 'plus': 'Plus', 'business': 'Business', 'auth': 'Staff roles',
}
SKIP = {'auth.permission'}

# Never sent to the browser, for anyone.
SECRET_RE = re.compile(r'(^password$|token|secret|_hash$|_enc$|^stripe_payment_method$|^client_id$)')
# Private conversations: admins only.
PRIVATE = {
    'messaging.message': {'text'},
    'messaging.conversation': {'last_message_text'},
    'chats.chatmessage': {'body', 'share', 'latitude', 'longitude', 'photo', 'attachment'},
}
# Records nobody creates by hand here (the app or other flows make them).
NO_CREATE = {'users.user', 'auth.group'}
TEXT_TYPES = (models.CharField, models.TextField, models.EmailField)


def model_for(label):
    try:
        m = apps.get_model(label)
    except (LookupError, ValueError):
        return None
    return m if key(m) not in SKIP and m._meta.app_label in APPS else None


def key(m):
    return f'{m._meta.app_label}.{m._meta.model_name}'


def all_models():
    return [m for m in apps.get_models() if m._meta.app_label in APPS and key(m) not in SKIP]


def can(user, action, m):
    if not (user.is_active and user.is_staff):
        return False
    if user.is_superuser:
        return True
    if action in ('add', 'delete') and key(m) == 'users.user':
        return False
    return user.has_perm(f'{m._meta.app_label}.{action}_{m._meta.model_name}')


def perms(user, m):
    return {a: can(user, a, m) for a in ('view', 'change', 'add', 'delete')} | {
        'add': can(user, 'add', m) and key(m) not in NO_CREATE}


def hidden(user, m, f):
    if SECRET_RE.search(f.name):
        return 'secret'
    if f.name in PRIVATE.get(key(m), ()) and not user.is_superuser:
        return 'private'
    return None


def fields(m):
    return [f for f in m._meta.concrete_fields]


def label(obj, n=80):
    try:
        s = str(obj)
    except Exception:  # noqa: BLE001 - a broken __str__ must not break the dashboard
        s = ''
    s = s or f'#{obj.pk}'
    return s if len(s) <= n else s[:n - 1] + '…'


def kind(f):
    if f.is_relation:
        return 'fk'
    if f.choices:
        return 'choice'
    if isinstance(f, models.BooleanField):
        return 'bool'
    if isinstance(f, models.DateTimeField):
        return 'datetime'
    if isinstance(f, models.DateField):
        return 'date'
    if isinstance(f, (models.IntegerField, models.FloatField, models.DecimalField)):
        return 'number'
    if isinstance(f, models.JSONField):
        return 'json'
    if isinstance(f, models.FileField):
        return 'file'
    if isinstance(f, models.TextField):
        return 'text'
    return 'string'


def value(user, m, obj, f):
    h = hidden(user, m, f)
    if h:
        return {'hidden': h}
    if f.is_relation:
        rid = getattr(obj, f.attname)
        if rid is None:
            return None
        rel = getattr(obj, f.name, None)
        return {'id': rid, 'label': label(rel) if rel is not None else f'#{rid}', 'model': key(f.related_model)}
    v = getattr(obj, f.attname)
    if isinstance(f, models.FileField):
        return v.url if v else None
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, (decimal.Decimal, uuid.UUID)):
        return str(v)
    if isinstance(v, datetime.timedelta):
        return v.total_seconds()
    if isinstance(v, (bytes, memoryview)):
        return {'hidden': 'binary'}
    if isinstance(v, str) and len(v) > 4000:
        return v[:4000] + '…'
    return v


def meta_field(user, m, f):
    d = {'name': f.name, 'label': str(f.verbose_name)[:1].upper() + str(f.verbose_name)[1:], 'type': kind(f),
         'editable': bool(f.editable and not f.primary_key and not getattr(f, 'auto_now', False)
                          and not getattr(f, 'auto_now_add', False) and not hidden(user, m, f)
                          and kind(f) != 'file'),
         'null': f.null, 'blank': f.blank, 'help': str(f.help_text or '')}
    if f.choices:
        d['choices'] = [[str(k), str(v)] for k, v in f.flatchoices]
    if f.is_relation:
        d['model'] = key(f.related_model)
    if hidden(user, m, f):
        d['hidden'] = hidden(user, m, f)
    return d


def columns(m):
    """What a list shows: the Django admin's list_display where it names real
    fields, else the most telling fields."""
    names = {f.name for f in fields(m)}
    ma = admin.site._registry.get(m)
    picked = []
    if ma:
        picked = [c for c in ma.list_display if isinstance(c, str) and c in names]
    if len(picked) < 2:
        def score(f):
            n = f.name
            if f.primary_key:
                return -1
            if n in ('name', 'title', 'email', 'display_name', 'label'):
                return 0
            if f.is_relation:
                return 1
            if f.choices or isinstance(f, models.BooleanField):
                return 2
            if n in ('created_at', 'start_time', 'date', 'joined_at'):
                return 3
            if isinstance(f, (models.JSONField, models.TextField)):
                return 9
            return 5
        picked = [f.name for f in sorted(fields(m), key=score) if not SECRET_RE.search(f.name)][:6]
    pk = m._meta.pk.name
    return [pk] + [c for c in picked if c != pk][:7]


def search_fields(m):
    ma = admin.site._registry.get(m)
    if ma and ma.search_fields:
        return [s.lstrip('^=@') for s in ma.search_fields]
    return [f.name for f in fields(m) if isinstance(f, TEXT_TYPES) and not SECRET_RE.search(f.name)][:6]


def filters(m):
    out = []
    for f in fields(m):
        if f.choices or isinstance(f, models.BooleanField):
            out.append({'name': f.name, 'label': str(f.verbose_name).capitalize(),
                        'choices': [[str(k), str(v)] for k, v in f.flatchoices] if f.choices
                        else [['true', 'Yes'], ['false', 'No']]})
    return out[:6]


def summary(user, m):
    o = m._meta
    return {'key': key(m), 'app': o.app_label, 'app_label': APP_LABELS.get(o.app_label, o.app_label),
            'name': str(o.verbose_name_plural).capitalize(), 'single': str(o.verbose_name).capitalize(),
            'perms': perms(user, m)}
