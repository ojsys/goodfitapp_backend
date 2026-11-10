"""Local staff accounts for trying the staff dashboard (/staff/).

    python3 manage.py seed_staff

admin@test.agoodfit.app (admin) and staff@test.agoodfit.app (staff), with the
seed password used by the other seed commands. Development only. Also adds
one open report and one support message so the queues have something in them.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from apps.staff import roles

PASSWORD = 'goodfit123'


class Command(BaseCommand):
    help = 'Create local admin and staff accounts for the staff dashboard (DEBUG only).'

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError('seed_staff only runs with DEBUG on.')
        roles.sync()
        User = get_user_model()
        out = []
        for email, first, admin in [('admin@test.agoodfit.app', 'Avery', True), ('staff@test.agoodfit.app', 'Sam', False)]:
            u, _ = User.objects.get_or_create(email=email, defaults={'first_name': first})
            u.first_name, u.is_staff, u.is_superuser, u.is_active = first, True, admin, True
            u.set_password(PASSWORD)
            u.save()
            if not admin:
                u.groups.add(Group.objects.get(name='Staff'))
            out.append(f'{email} ({"admin" if admin else "staff"})')

        from apps.safety.models import Report, SupportMessage
        member = User.objects.filter(is_staff=False, is_active=True).order_by('id').first()
        other = User.objects.filter(is_staff=False, is_active=True).exclude(pk=getattr(member, 'pk', None)).order_by('id').first()
        if member and other and not Report.objects.filter(status='open', details__startswith='[seed]').exists():
            Report.objects.create(reporter=other, target_kind='member', target_user=member, reason='harassment',
                                  context='Fit Buddies profile', snapshot='“Keep messaging me back or else.”',
                                  details='[seed] Kept messaging after I said no.')
        if member and not SupportMessage.objects.filter(text__startswith='[seed]').exists():
            SupportMessage.objects.create(user=member, topic='question', text='[seed] How do I change my neighborhood?')
        self.stdout.write(self.style.SUCCESS('Staff accounts: ' + ', '.join(out) + '. Open /staff/.'))
