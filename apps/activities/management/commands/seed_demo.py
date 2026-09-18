"""
Populate an account with demo activities and events so the app has something
to show.

    python manage.py seed_demo --email you@example.com

Everything it creates is tagged, so it can be removed cleanly:

    python manage.py seed_demo --email you@example.com --clear

This is sample data, not real history. Use it to see the app populated; clear
it before the account belongs to an actual person.
"""

import io
import math
import os
import random
from datetime import timedelta

from django.core.files.base import ContentFile
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.activities.models import Activity
from apps.events.models import Event
from apps.matching.models import UserProfile as MatchingProfile
from apps.messaging.models import Conversation, Message

User = get_user_model()

# Every seeded row carries this marker so --clear can find them again.
#
# It lives in fields the app does not put on screen -- an activity's notes, an
# event's description -- rather than in titles. A card reading
# "Saturday club ride [demo]" makes a finished app look like scaffolding.
MARKER = '[demo]'

# Demo accounts live on a reserved domain that can never receive mail, so they
# are trivially identifiable and cannot collide with a real sign-up.
DEMO_DOMAIN = 'demo.goodfit.invalid'

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

# App-wide demo people. Everyone sees these in Fit Buddies, so a new account
# does not open to an empty screen. Names are ordinary on purpose -- a card
# reading "Demo User 1" makes the whole app look unfinished.
DEMO_PEOPLE = [
    ('Marvel Marcel', 28, 'male', 'intermediate',
     ['Cycle', 'Run'], ['Endurance'],
     'Ask me about my post-ride bagel order.'),
    ('Shari Brown', 31, 'female', 'advanced',
     ['Run', 'Yoga'], ['Stay Healthy'],
     'Training for my third marathon, slowly.'),
    ('Drew Bennett', 26, 'male', 'intermediate',
     ['Cycle', 'Strength'], ['Build Muscle'],
     'Will ride any distance for good coffee.'),
    ('Nia Cole', 34, 'female', 'beginner',
     ['Walk', 'Yoga'], ['Stay Healthy'],
     'Just started and looking for gentle company.'),
    ('Sam Kwon', 29, 'other', 'advanced',
     ['Run', 'Swim'], ['Endurance'],
     'Early mornings only. Sorry.'),
    ('Priya Raman', 27, 'female', 'intermediate',
     ['Run', 'Strength'], ['Build Muscle'],
     'Parkrun every Saturday, rain or shine.'),
    ('Tom Okafor', 35, 'male', 'beginner',
     ['Walk', 'Cycle'], ['Lose Weight'],
     'Getting back into it after a long break.'),
    ('Elena Duarte', 30, 'female', 'advanced',
     ['Swim', 'Cycle'], ['Endurance'],
     'Triathlon in the spring. Send help.'),
    ('Jonas Meyer', 24, 'male', 'intermediate',
     ['Strength', 'Run'], ['Build Muscle'],
     'Gym in the morning, trails at the weekend.'),
    ('Aisha Bello', 32, 'female', 'intermediate',
     ['Yoga', 'Walk'], ['Stay Healthy'],
     'Sunrise yoga is the best part of my day.'),
]

# Opening exchanges, so the chat tab has real threads to test against.
CONVERSATIONS = [
    [
        ('them', 'Morning! Still on for the park loop Saturday?'),
        ('me', 'Yes -- 7am at the gate?'),
        ('them', 'Perfect. I will bring a spare tube just in case.'),
    ],
    [
        ('them', 'That tempo session looked quick. What pace were you holding?'),
        ('me', 'Around 7:30s. Felt harder than it looked.'),
    ],
    [
        ('them', 'Fancy an easy recovery walk later in the week?'),
    ],
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


# The Earth palette, so generated imagery matches the app rather than looking
# like stock filler dropped in from elsewhere.
AVATAR_RAMPS = [
    ((150, 168, 104), (94, 114, 51)),
    ((209, 154, 108), (166, 95, 46)),
    ((192, 149, 124), (138, 92, 70)),
    ((169, 181, 131), (110, 128, 70)),
    ((212, 168, 140), (177, 112, 90)),
    ((143, 165, 160), (92, 122, 115)),
]

FONT_CANDIDATES = [
    os.path.join(
        os.path.dirname(__file__),
        '../../../../../mygoodfit_app/assets/fonts/PlayfairDisplay-Bold.ttf',
    ),
    '/System/Library/Fonts/Supplemental/Georgia Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf',
    '/usr/share/fonts/dejavu/DejaVuSerif-Bold.ttf',
]


def _font(size):
    """The nicest serif available, falling back to Pillow's bitmap font.

    Hosts differ wildly in what fonts they ship, and a missing font should
    degrade the image rather than fail the whole seed.
    """
    from PIL import ImageFont

    for path in FONT_CANDIDATES:
        resolved = os.path.abspath(path)
        if os.path.exists(resolved):
            try:
                return ImageFont.truetype(resolved, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _gradient(size, top, bottom, diagonal=True):
    """A simple linear gradient image."""
    from PIL import Image

    width, height = size
    base = Image.new('RGB', (width, height))
    pixels = base.load()
    span = (width + height) if diagonal else height

    for y in range(height):
        for x in range(width):
            t = ((x + y) / span) if diagonal else (y / max(height - 1, 1))
            pixels[x, y] = (
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
            )
    return base


def make_avatar(name, index, size=400):
    """A circular-ready avatar: initials over a palette gradient.

    Generated rather than pulled from a stock-photo service: these are
    invented people, and putting a real person's face on a fabricated profile
    is not something to do casually.
    """
    from PIL import ImageDraw

    top, bottom = AVATAR_RAMPS[index % len(AVATAR_RAMPS)]
    image = _gradient((size, size), top, bottom)
    draw = ImageDraw.Draw(image)

    initials = ''.join(part[0] for part in name.split()[:2]).upper()
    font = _font(int(size * 0.38))
    box = draw.textbbox((0, 0), initials, font=font)
    draw.text(
        ((size - (box[2] - box[0])) / 2 - box[0],
         (size - (box[3] - box[1])) / 2 - box[1]),
        initials,
        font=font,
        fill=(255, 255, 255),
    )

    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


def make_cover(title, index, size=(1200, 800)):
    """An event cover: gradient with the event name set in serif."""
    from PIL import ImageDraw

    top, bottom = AVATAR_RAMPS[(index + 2) % len(AVATAR_RAMPS)]
    image = _gradient(size, top, bottom, diagonal=False)
    draw = ImageDraw.Draw(image)

    # Darken the lower half so the title stays legible.
    width, height = size
    for y in range(height // 2, height):
        alpha = (y - height // 2) / (height / 2)
        draw.line(
            [(0, y), (width, y)],
            fill=(
                int(top[0] * (1 - alpha * 0.55)),
                int(top[1] * (1 - alpha * 0.55)),
                int(top[2] * (1 - alpha * 0.55)),
            ),
        )

    font = _font(72)
    draw.text((64, height - 180), title, font=font, fill=(255, 255, 255))

    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


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
        parser.add_argument(
            '--base-url', default='http://127.0.0.1:8000',
            help=(
                'Origin used to build absolute image URLs, e.g. '
                'https://goodfit.example.com'
            ),
        )
        parser.add_argument(
            '--people', action='store_true',
            help=(
                'Also create app-wide demo people so every account has '
                'someone to discover in Fit Buddies'
            ),
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
        base_url = options['base_url']
        created = 0

        if options['people']:
            self._seed_people(user, now, rng)
            self._seed_conversations(user, now)

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
                title=title,
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

            # Covers are written straight into MEDIA_ROOT; image_url needs an
            # absolute URL because the app loads it over the network.
            cover_url = ''
            media_root = getattr(settings, 'MEDIA_ROOT', '')
            if media_root:
                folder = os.path.join(media_root, 'events')
                os.makedirs(folder, exist_ok=True)
                filename = f'demo-event-{offset}.png'
                with open(os.path.join(folder, filename), 'wb') as handle:
                    handle.write(make_cover(title, offset))
                media_url = getattr(settings, 'MEDIA_URL', '/media/')
                cover_url = f"{base_url.rstrip('/')}{media_url}events/{filename}"

            Event.objects.create(
                title=title,
                description=f'Sample event for demo purposes. {MARKER}',
                image_url=cover_url,
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

    def _seed_people(self, user, now, rng):
        """Create shared demo accounts with matching profiles and activities.

        These belong to nobody in particular -- they exist so a brand-new user
        sees a populated app instead of empty screens.

        They are placed near the seeded account, because discovery filters by
        distance: people seeded at a fixed location are invisible to anyone
        living elsewhere, which looks identical to the feature being broken.
        """
        anchor_lat, anchor_lng = CENTRE_LAT, CENTRE_LNG
        anchor_city = 'Brooklyn, NY'

        profile = MatchingProfile.objects.filter(user=user).first()
        if profile and profile.latitude and profile.longitude:
            anchor_lat, anchor_lng = profile.latitude, profile.longitude
            anchor_city = profile.location_city or anchor_city
            self.stdout.write(
                f'Placing demo people near {anchor_city} '
                f'({anchor_lat:.3f}, {anchor_lng:.3f})'
            )

        self.stdout.write('App-wide demo people:')

        for index, (name, age, gender, level, activities, goals, prompt) \
                in enumerate(DEMO_PEOPLE):
            email = f"{name.split()[0].lower()}.{index}@{DEMO_DOMAIN}"
            person, was_created = User.objects.get_or_create(
                email=email,
                defaults={'display_name': name, 'bio': prompt},
            )
            if was_created:
                # No usable password: these accounts exist to be looked at,
                # not signed into.
                person.set_unusable_password()
                person.save(update_fields=['password'])

            # Give them a face so the photo path is exercised, not just the
            # initials fallback.
            if not person.avatar:
                person.avatar.save(
                    f'demo-{index}.png',
                    ContentFile(make_avatar(name, index)),
                    save=True,
                )

            MatchingProfile.objects.update_or_create(
                user=person,
                defaults={
                    'age': age,
                    'gender': gender,
                    'location_city': anchor_city,
                    'fitness_level': level,
                    'favorite_activities': activities,
                    'fitness_goals': goals,
                    'looking_for': ['workout_partner'],
                    'prompt_question': prompt,
                    # Within roughly three miles, so they clear the default
                    # 25-mile discovery radius comfortably.
                    'latitude': anchor_lat + rng.uniform(-0.04, 0.04),
                    'longitude': anchor_lng + rng.uniform(-0.04, 0.04),
                    'is_active': True,
                },
            )

            # A little history each, so their profiles are not hollow.
            if not Activity.objects.filter(user=person).exists():
                for offset in range(2):
                    kind, title, minutes, metres, climb = SESSIONS[
                        (index + offset) % len(SESSIONS)
                    ]
                    started = now - timedelta(days=offset * 3 + 1)
                    Activity.objects.create(
                        user=person,
                        type=kind,
                        title=title,
                        start_time=started,
                        end_time=started + timedelta(minutes=minutes),
                        duration=minutes,
                        distance=metres or None,
                        elevation_gain=climb or None,
                        notes=f'Sample data {MARKER}',
                        route=build_route(metres, started, minutes, rng),
                    )

            self.stdout.write(f'  person: {name} ({"created" if was_created else "updated"})')

    def _seed_conversations(self, user, now):
        """Give the account a few threads with the demo people."""
        people = list(
            User.objects.filter(email__endswith=f'@{DEMO_DOMAIN}').order_by('pk')
        )
        if not people:
            return

        self.stdout.write('Conversations:')
        for index, script in enumerate(CONVERSATIONS):
            if index >= len(people):
                break
            other = people[index]

            # get_or_create on the pair keeps re-runs from stacking duplicates.
            conversation, created = Conversation.objects.get_or_create(
                participant1=user, participant2=other,
            )
            if not created and conversation.messages.exists():
                self.stdout.write(f'  thread with {other.display_name} (exists)')
                continue

            for offset, (who, text) in enumerate(script):
                Message.objects.create(
                    conversation=conversation,
                    sender=user if who == 'me' else other,
                    text=text,
                    # Space them a few minutes apart so the thread reads in
                    # order and the day dividers make sense.
                    created_at=now - timedelta(hours=index + 1, minutes=10 - offset * 3),
                )

            last = conversation.messages.order_by('-created_at').first()
            if last:
                conversation.last_message_text = last.text
                conversation.last_message_at = last.created_at
                conversation.last_message_sender = last.sender
                conversation.save(update_fields=[
                    'last_message_text', 'last_message_at', 'last_message_sender',
                ])

            self.stdout.write(f'  thread with {other.display_name}')

    def _clear(self, user):
        activities = Activity.objects.filter(user=user, notes__contains=MARKER)
        events = Event.objects.filter(host=user, description__contains=MARKER)
        counts = (activities.count(), events.count())

        # Deleting through the queryset skips Activity.delete(), which is what
        # rolls the user's totals back, so remove them one at a time.
        for activity in activities:
            activity.delete()
        events.delete()

        # Remove the shared demo accounts too. Deleting the user cascades to
        # their profile, activities and any conversations they appear in.
        demo_people = User.objects.filter(email__endswith=f'@{DEMO_DOMAIN}')
        people_count = demo_people.count()
        demo_people.delete()

        self.stdout.write(self.style.SUCCESS(
            f'Removed {counts[0]} demo activities, {counts[1]} demo events '
            f'and {people_count} demo people.'
        ))
