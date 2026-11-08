"""
Development data for A Good Match: Camille and Theo (from the screens),
their prompts and habits, and two first-date events. Turns on Romantic for
--member and resets their matches, so the flow can be run again.

    python manage.py seed_match --member you@example.com

Camille has already liked the member, so liking her back locks the match.
Refuses to run unless DEBUG is on.
"""

import datetime as dt
import zoneinfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.activities.models import Activity
from apps.chats.models import Chat
from apps.events.models import Event
from apps.users.age_gate import encrypt_birthday
from apps.users.models import User

from ...models import Decision, Match, MatchProfile

DOMAIN = 'demo.agoodfit.app'
NY = zoneinfo.ZoneInfo('America/New_York')

PEOPLE = {
    'camille': dict(first='Camille', last='Laurent', age=31, hood='Fort Greene', at=(40.6880, -73.9760),
                    interests=['cycling', 'yoga'], gender='woman', pace='Easy, chatty', verified=True,
                    kind='ride', per_week=3, hour=7, mps=6.7, km=24,
                    prompts=[{'q': 'My ideal Sunday', 'a': 'A long ride to Coney Island, then dumplings on the '
                              'walk home.'},
                             {'q': 'The way to win me over', 'a': 'Know a good coffee stop on any route.'}]),
    'theo': dict(first='Theo', last='Owens', age=29, hood='Park Slope', at=(40.6740, -73.9790),
                 interests=['running', 'hiking', 'cycling'], gender='man', pace='Easy-going', verified=True,
                 kind='run', per_week=4, hour=8, mps=3.15, km=8,
                 prompts=[{'q': 'Typical Saturday', 'a': 'Run Club, a big breakfast, then a trail somewhere '
                           'upstate.'},
                          {'q': 'Looking for', 'a': 'Someone who will say yes to a 6 AM sunrise run.'}]),
}


def birthday_for(age):
    today = timezone.now().astimezone(NY).date()
    return today.replace(year=today.year - age) - dt.timedelta(days=40)


class Command(BaseCommand):
    help = 'Seed A Good Match development data (DEBUG only).'

    def add_arguments(self, parser):
        parser.add_argument('--member', required=True, help='Email of your test account.')

    def handle(self, *args, **o):
        if not settings.DEBUG:
            raise CommandError('seed_match only runs with DEBUG on.')
        me = User.objects.filter(email=o['member']).first()
        if me is None:
            raise CommandError(f'No account for {o["member"]}.')
        now = timezone.now()
        people = {}
        for key, p in PEOPLE.items():
            u, created = User.objects.get_or_create(email=f'{key}@{DOMAIN}', defaults=dict(
                first_name=p['first'], last_name=p['last'], photo_step_done=True, guidelines_agreed_at=now,
                guidelines_version=settings.GUIDELINES_VERSION, timezone='America/New_York'))
            if created:
                u.set_password('goodfit123')
            u.birthday_enc = encrypt_birthday(birthday_for(p['age']))
            u.neighborhood = p['hood']
            u.interests = p['interests']
            u.intents = ['community', 'romantic']
            u.approx_lat, u.approx_lng = p['at']
            u.id_verified = p['verified']
            u.match_paused = False
            u.save()
            MatchProfile.objects.update_or_create(user=u, defaults=dict(
                gender=p['gender'], show_me='everyone', prompts=p['prompts'], pace_note=p['pace'],
                cooldown_until=None))
            if not Activity.objects.filter(user=u, type=p['kind'], start_time__gte=now - dt.timedelta(days=27)).exists():
                self._habits(u, p, now)
            people[key] = u

        # The member: Romantic on, a match profile, a clean slate.
        if 'romantic' not in (me.intents or []):
            me.intents = list(me.intents or []) + ['romantic']
        if 'yoga' not in (me.interests or []) and len(me.interests or []) < 3:
            me.interests = list(me.interests or []) + ['yoga']
        me.match_paused = False
        if not me.approx_lat:
            me.approx_lat, me.approx_lng = 40.6710, -73.9814
        me.save()
        mp = MatchProfile.of(me)
        mp.cooldown_until = None
        if not mp.gender:
            mp.gender = 'woman'
        if not mp.prompts:
            mp.prompts = [{'q': 'Green flag on a first date', 'a': 'Suggesting we walk the long way back.'}]
        mp.save()
        everyone = [me] + list(people.values())
        old = Match.objects.filter(a__in=everyone, b__in=everyone)
        Chat.objects.filter(id__in=old.exclude(chat=None).values('chat_id')).delete()
        old.delete()
        Decision.objects.filter(actor__in=everyone, target__in=everyone).delete()
        Decision.objects.create(actor=people['camille'], target=me, action='like')

        # First-date ideas: open events near both of them.
        today = now.astimezone(NY).date()
        thu = today + dt.timedelta(days=(3 - today.weekday()) % 7 or 7)
        sat = today + dt.timedelta(days=(5 - today.weekday()) % 7 or 7)
        for title, day, hh, mm, kind, place, lat, lng in [
            ('Sunset Yoga in the Park', thu, 17, 30, 'yoga', 'Flow Studio', 40.6800, -73.9770),
            ('Halloween Glow Walk', sat, 18, 0, 'walk', 'Prospect Park', 40.6602, -73.9690),
        ]:
            start = dt.datetime.combine(day, dt.time(hh, mm), tzinfo=NY)
            Event.objects.update_or_create(title=title, defaults=dict(
                description='', host=people['camille'], host_name='Flow Studio' if kind == 'yoga' else 'Prospect Park',
                vibe='Social', start_time=start, location_name=place, location_address='Brooklyn, NY',
                latitude=lat, longitude=lng, kind='community', activity_type=kind, who_can_join='anyone',
                level='easy', duration_min=60, is_active=True, is_cancelled=False))
        self.stdout.write(self.style.SUCCESS(
            f'A Good Match ready for {me.email}: Camille (likes you) and Theo. Romantic is on.'))

    def _habits(self, u, p, now):
        weeks, n = 4, p['per_week']
        for w in range(weeks):
            for i in range(n):
                day = (now - dt.timedelta(days=7 * w + 1 + i * 2)).astimezone(NY)
                start = day.replace(hour=p['hour'], minute=0, second=0, microsecond=0)
                if p['kind'] == 'run' and i == 0:
                    start = start - dt.timedelta(days=(start.weekday() - 5) % 7)  # a weekend run
                dist = p['km'] * 1000
                moving = int(dist / p['mps'])
                Activity.objects.create(user=u, type=p['kind'], title='Morning ' + p['kind'], start_time=start,
                                        duration=moving // 60, moving_time=moving, elapsed_time=moving + 60,
                                        distance=dist, average_speed=p['mps'] * 3.6, visibility='followers')
