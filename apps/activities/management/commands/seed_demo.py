"""
Populate an account with demo activities and events so the app has something
to show.

    python manage.py seed_demo --email you@example.com

Everything it creates is tagged, so it can be removed cleanly:

    python manage.py seed_demo --email you@example.com --clear

This is sample data, not real history. Use it to see the app populated; clear
it before the account belongs to an actual person.
"""

import math
import random
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.activities.models import Activity
from apps.events.models import Event

User = get_user_model()

# Every seeded row carries this marker so --clear can find them again.
MARKER = '[demo]'

# A loop through Prospect Park, Brooklyn.
CENTRE_LAT = 40.6602
CENTRE_LNG = -73.9690

SESSIONS = [
    ('Run', 'Golden hour loop before the heat', 38, 8043, 96),
    ('Run', 'Easy shakeout', 24, 4180, 38),
    ('Cycle', 'Long way round to the coffee place', 72, 24140, 210),
    ('Cycle', 'Saturday club ride', 104, 41200, 315),
    ('Walk', 'Evening wander', 45, 3900, 22),
    ('Yoga', 'Mobility reset after a heavy week', 42, 0, 0),
    ('Strength', 'Push day', 55, 0, 0),
    ('Run', 'Tempo intervals in the park', 46, 9660, 120),
]

EVENTS = [
    ('Rockaway Beach Ride', 'GoodCo Bike Club', 'Moderate',
     'Rockaway Beach', 'Beach 90th St, Queens, NY', 18),
    ('Sunset Yoga in the Park', 'Flow Studio', 'Chill',
     'Prospect Park Long Meadow', 'Prospect Park West, Brooklyn, NY', 25),
    ('Track Night 5K', 'Brooklyn Runners', 'Intense',
     'Red Hook Track', 'Bay St, Brooklyn, NY', 40),
    ('Saturday Coffee Social', 'A Good Fit', 'Social',
     'Grand Army Plaza', 'Grand Army Plaza, Brooklyn, NY', None),
]


def build_route(distance_metres, started_at, duration_minutes, rng):
    """A plausible GPS track: a closed loop with gentle elevation.

    Points carry timestamps and altitude so the app's splits, elevation
    profile and best-effort analysis have real values to work from.
    """
    if distance_metres <= 0:
        return None

    # One point roughly every five seconds, as a phone would record.
    count = max(24, int(duration_minutes * 60 / 5))
    # Rough degrees for the loop radius at this latitude.
    radius = (distance_metres / (2 * math.pi)) / 111_320

    points = []
    for i in range(count):
        t = i / (count - 1)
        angle = t * 2 * math.pi
        wobble = 1 + 0.06 * math.sin(angle * 3 + rng.random())
        points.append({
            'latitude': CENTRE_LAT + radius * wobble * math.sin(angle),
            'longitude': CENTRE_LNG + radius * wobble * math.cos(angle) * 0.78,
            'altitude': 18 + 12 * math.sin(angle * 2) + 4 * math.sin(angle * 5),
            'speed': distance_metres / max(duration_minutes * 60, 1),
            'timestamp': (
                started_at + timedelta(seconds=int(t * duration_minutes * 60))
            ).isoformat(),
        })
    return points


class Command(BaseCommand):
    help = 'Create demo activities and events for an account.'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True, help='Account to seed')
        parser.add_argument(
            '--clear', action='store_true',
            help='Remove previously seeded demo data instead of creating more',
        )
        parser.add_argument(
            '--activities', type=int, default=8,
            help='How many activities to create (default 8)',
        )

    def handle(self, *args, **options):
        email = options['email']
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(
                f'No account with email {email}. '
                f'Existing: {", ".join(User.objects.values_list("email", flat=True)) or "none"}'
            )

        if options['clear']:
            return self._clear(user)

        rng = random.Random(user.pk)
        now = timezone.now()
        created = 0

        wanted = min(options['activities'], len(SESSIONS))
        for index in range(wanted):
            kind, title, minutes, metres, climb = SESSIONS[index]

            # Spread them over the past fortnight, at plausible hours.
            started = (now - timedelta(days=index * 2, hours=rng.randint(0, 6))).replace(
                hour=rng.choice([7, 8, 12, 18, 19]), minute=rng.choice([0, 15, 30]),
            )

            activity = Activity.objects.create(
                user=user,
                type=kind,
                title=f'{title} {MARKER}',
                start_time=started,
                end_time=started + timedelta(minutes=minutes),
                duration=minutes,
                distance=metres or None,
                elevation_gain=climb or None,
                average_speed=(metres / 1000) / (minutes / 60) if metres else None,
                calories_burned=int(minutes * rng.uniform(7, 11)),
                notes=f'Sample data {MARKER}',
                route=build_route(metres, started, minutes, rng),
                start_latitude=CENTRE_LAT if metres else None,
                start_longitude=CENTRE_LNG if metres else None,
            )
            created += 1
            self.stdout.write(f'  activity: {activity.title}')

        for offset, (title, host_name, vibe, place, address, cap) in enumerate(EVENTS):
            start = now + timedelta(days=offset + 1, hours=rng.randint(0, 5))
            Event.objects.create(
                title=f'{title} {MARKER}',
                description=f'Sample event for demo purposes. {MARKER}',
                host=user,
                host_name=host_name,
                vibe=vibe,
                price_type='Free',
                start_time=start,
                end_time=start + timedelta(hours=2),
                location_name=place,
                location_address=address,
                latitude=CENTRE_LAT,
                longitude=CENTRE_LNG,
                max_attendees=cap,
                tags=['demo'],
                what_to_bring=['Water', 'Good mood'],
            )
            self.stdout.write(f'  event: {title}')

        self.stdout.write(self.style.SUCCESS(
            f'\nSeeded {created} activities and {len(EVENTS)} events for {email}.'
            f'\nRemove them later with:  python manage.py seed_demo --email {email} --clear'
        ))

    def _clear(self, user):
        activities = Activity.objects.filter(user=user, title__contains=MARKER)
        events = Event.objects.filter(host=user, title__contains=MARKER)
        counts = (activities.count(), events.count())

        # Deleting through the queryset skips Activity.delete(), which is what
        # rolls the user's totals back, so remove them one at a time.
        for activity in activities:
            activity.delete()
        events.delete()

        self.stdout.write(self.style.SUCCESS(
            f'Removed {counts[0]} demo activities and {counts[1]} demo events.'
        ))
