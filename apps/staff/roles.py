"""The "Staff" group: what staff (not admins) can do.

View every model, and act on the review queues: reports, support messages,
featured events, business verification, and suspending or reinstating
members. Admins (superusers) can do everything, including editing or
deleting any record and managing the team. Kept in sync after every migrate.
"""

from django.contrib.auth.models import Group, Permission

ACT_ON = [
    ('safety', 'change_report'), ('safety', 'change_supportmessage'), ('safety', 'add_moderationaction'),
    ('business', 'change_featuredplacement'), ('business', 'change_businessaccount'),
    ('users', 'change_user'),
]


def sync(**kwargs):
    from .registry import APPS
    g, _ = Group.objects.get_or_create(name='Staff')
    want = set(Permission.objects.filter(content_type__app_label__in=[a for a in APPS if a != 'auth'],
                                         codename__startswith='view_'))
    for app, code in ACT_ON:
        want.update(Permission.objects.filter(content_type__app_label=app, codename=code))
    g.permissions.add(*want)
