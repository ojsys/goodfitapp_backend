"""
Development data for A Good Fit Plus: puts --member back on the free plan
(removes their subscriptions, so the free trial shows again) and posts a
capped ride that has just gone up, so only Plus members can RSVP yet.

    python manage.py seed_plus --member you@example.com

Refuses to run unless DEBUG is on.
"""

import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.events.models import Event
from apps.users.models import User

from ...models import Subscription
from ...services import refresh_plan

TITLE = 'Bagel Ride to Bed-Stuy'


class Command(BaseCommand):
    help = 'Seed A Good Fit Plus development data (DEBUG only).'

    def add_arguments(self, parser):
        parser.add_argument('--member', required=True, help='Email of your test account.')

    def handle(self, *args, **o):
        if not settings.DEBUG:
            raise CommandError('seed_plus only runs with DEBUG on.')
        me = User.objects.filter(email=o['member']).first()
        if me is None:
            raise CommandError(f'No member {o["member"]}.')
        Subscription.objects.filter(user=me).delete()
        refresh_plan(me)
        host = User.objects.exclude(pk=me.pk).filter(is_active=True, guidelines_agreed_at__isnull=False).first() or me
        Event.objects.filter(title=TITLE).delete()
        start = (timezone.now() + dt.timedelta(days=5)).replace(hour=14, minute=0, second=0, microsecond=0)
        Event.objects.create(
            title=TITLE, description='An easy 20 miles to the best bagels in Brooklyn. Capped at 12.',
            host=host, host_name=host.first_name or 'A Good Fit', leader=host, vibe='Social',
            start_time=start, location_name='Grand Army Plaza', location_address='Grand Army Plaza, Brooklyn',
            latitude=40.6743, longitude=-73.9702, activity_type='ride', kind='community', pace='Social pace',
            distance_m=32187, no_drop=True, max_attendees=12, tags=['cycling'])
        self.stdout.write(self.style.SUCCESS(f'{me.email} is on the free plan; "{TITLE}" opens to Plus first.'))
