"""Phase 7: segment matching, PRs, leaderboards, chasing, challenges,
trophies and training."""

import datetime as dt
import uuid
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from apps.activities.models import Activity
from apps.notifications.models import Notification
from apps.social.models import Club, ClubMembership, Follow
from apps.social.tests import Base, member

from . import challenges, matching, segments, training
from .models import Challenge, ChallengeEntry, Segment, SegmentEffort, Trophy

# A straight 1 km stretch going north from Grand Army Plaza.
START = (40.6700, -73.9700)
STEP = 0.0009  # ~100 m of latitude


def seg_line(n=10):
    return [[START[0] + i * STEP, START[1], 50 + i * 2] for i in range(n + 1)]


def track(seconds_per_100m, before=3, after=3, lng_off=0.0, t0=None):
    """Points every ~100 m from a bit before the segment to a bit after."""
    t0 = t0 or int(timezone.now().timestamp() * 1000) - 3_600_000
    pts = []
    for k, i in enumerate(range(-before, 10 + after + 1)):
        pts.append({'lat': START[0] + i * STEP, 'lng': START[1] + lng_off, 'alt': 50,
                    't': t0 + int(k * seconds_per_100m * 1000), 'seg': 0})
    return pts


class SegmentTests(Base):
    def setUp(self):
        super().setUp()
        self.seg = Segment.objects.create(name='Park Drive Sprint', area='Prospect Park, Brooklyn', line=seg_line())
        self.club = Club.objects.create(name='GoodCo Bike Club', initials='GC')
        for u in (self.me, self.friend, self.stranger):
            ClubMembership.objects.create(club=self.club, user=u)

    def upload(self, user, secs_per_100m, vis='everyone', **kw):
        c = self.client_for(user)
        r = c.post('/api/activities/record/', {
            'client_id': str(uuid.uuid4()), 'type': 'ride', 'title': 'Loop',
            'start_time': (timezone.now() - dt.timedelta(hours=1)).isoformat(), 'moving_time': 600,
            'elapsed_time': 600, 'visibility': vis, 'track': track(secs_per_100m, **kw)}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)
        return r.data

    def test_geometry_and_matching(self):
        self.assertAlmostEqual(self.seg.distance_m, 1000, delta=10)
        self.assertEqual(self.seg.avg_grade, 2.0)
        d = self.upload(self.me, 15)  # 15 s per 100 m = 1000 m in 150 s
        e = SegmentEffort.objects.get()
        self.assertEqual((e.elapsed_s, e.is_pr), (150, True))
        self.assertEqual(d['segments'][0]['badge'], 'PR')
        self.assertIn('New PR', d['segments'][0]['meta'])

    def test_off_course_and_car_speed_dont_count(self):
        self.upload(self.me, 15, lng_off=0.002)  # ~170 m to the east, parallel road
        self.upload(self.me, 2)  # 50 m/s
        self.assertFalse(SegmentEffort.objects.exists())

    def test_second_best_and_feed_count(self):
        self.upload(self.me, 15)
        d = self.upload(self.me, 15.4)
        self.assertEqual(d['segments'][0]['badge'], '2')
        self.assertIn('2nd best, 4s off PR', d['segments'][0]['meta'])
        feed = self.client_for(self.me).get('/api/social/feed/?tab=mine').data['items']
        self.assertEqual(sorted(i['segment_prs'] for i in feed if i['kind'] == 'activity'), [0, 1])

    def test_page_chase_and_passing_notification(self):
        self.upload(self.friend, 13)   # 130 s
        self.upload(self.stranger, 14)  # 140 s
        self.upload(self.me, 15)        # 150 s
        p = self.client_for(self.me).get(f'/api/performance/segments/{self.seg.id}/?scope=club').data
        self.assertEqual((p['record']['label'], p['record']['time'], p['record']['person']['first_name']),
                         ('Club Record', '2:10', 'Marvel'))
        self.assertEqual(p['pr']['time'], '2:30')
        self.assertIn('3rd in club', p['pr']['note'])
        self.assertEqual(p['chase']['title'], 'Beat 2:20 to pass Alex')
        self.assertEqual(p['chase']['note'], '10s faster than your PR moves you to 2nd')
        self.assertEqual([r['time'] for r in p['leaderboard']], ['2:10', '2:20', '2:30'])
        # Shari beats Alex: Alex hears about it.
        self.upload(self.me, 13.5)
        n = Notification.objects.filter(recipient=self.stranger, kind='segment').get()
        self.assertEqual(n.text, 'Shari is 5 seconds ahead of you on Park Drive Sprint. Beat 2:15 to move up to 2nd.')

    def test_private_efforts_stay_private(self):
        self.upload(self.friend, 13, vis='me')
        p = self.client_for(self.me).get(f'/api/performance/segments/{self.seg.id}/').data
        self.assertEqual(p['leaderboard'], [])
        p = self.client_for(self.friend).get(f'/api/performance/segments/{self.seg.id}/').data
        self.assertEqual(len(p['leaderboard']), 1)

    def test_following_scope_and_nearby_and_preview(self):
        self.upload(self.friend, 13)
        self.upload(self.stranger, 14)
        p = self.client_for(self.me).get(f'/api/performance/segments/{self.seg.id}/?scope=following').data
        self.assertEqual([r['person']['first_name'] for r in p['leaderboard']], ['Marvel'])
        n = self.client_for(self.me).get(f'/api/performance/segments/nearby/?lat={START[0]}&lng={START[1]}').data
        self.assertEqual(n['items'][0]['name'], 'Park Drive Sprint')
        self.upload(self.me, 15)
        pv = self.client_for(self.me).post('/api/performance/preview/', {'type': 'ride', 'track': track(14)},
                                          format='json').data
        self.assertEqual(pv['items'][0]['text'], 'New PR on Park Drive Sprint')
        pv = self.client_for(self.me).post('/api/performance/preview/', {'type': 'ride', 'track': track(15.4)},
                                          format='json').data
        self.assertEqual(pv['items'][0]['text'], 'Park Drive Sprint: 2nd best time, 4s off your PR')

    def test_backfill_command(self):
        self.upload(self.me, 15)
        seg2 = Segment.objects.create(name='Second Half', line=seg_line()[5:])
        out = StringIO()
        call_command('match_segments', '--segment', str(seg2.id), stdout=out)
        self.assertIn('1 effort(s) added', out.getvalue())
        self.assertTrue(SegmentEffort.objects.filter(segment=seg2).exists())


class ChallengeTests(Base):
    def challenge(self, **kw):
        now = timezone.now()
        return Challenge.objects.create(**{'title': 'Ride 500 miles', 'kind': 'distance', 'target': 500 * 1609.344,
                                           'starts_at': now - dt.timedelta(days=27), 'ends_at': now + dt.timedelta(days=3),
                                           'featured': True, 'trophy_label': '500 mi', 'activity_types': ['ride'],
                                           **kw})

    def test_featured_progress_rank_and_trophy(self):
        ch = self.challenge(target=10 * 1609.344)
        for u in (self.me, self.friend):
            ChallengeEntry.objects.create(challenge=ch, user=u)
        self.act(self.me, distance=8 * 1609.344)
        self.act(self.friend, distance=9 * 1609.344)
        p = self.client_for(self.me).get('/api/performance/challenges/').data
        f = p['featured']
        self.assertEqual((f['pct'], f['of_line'], f['rank'], f['joined_count']), (80, '8 of 10 mi', 2, 2))
        self.assertIn('3 days left', f['left_line'])
        self.act(self.me, distance=3 * 1609.344)
        challenges.update_for(self.me)
        self.assertEqual(Trophy.objects.get(user=self.me).label, '500 mi')
        self.assertTrue(Notification.objects.filter(recipient=self.me, kind='challenge').exists())

    def test_join_browse_and_nudge(self):
        ch = self.challenge(featured=False)
        p = self.client_for(self.me).get('/api/performance/challenges/').data
        self.assertEqual([c['title'] for c in p['browse']], ['Ride 500 miles'])
        p = self.client_for(self.me).post(f'/api/performance/challenges/{ch.id}/join/').data
        self.assertEqual([c['title'] for c in p['running']], ['Ride 500 miles'])
        self.act(self.me, distance=448 * 1609.344)
        self.assertEqual(challenges.nudge_ending(), 1)
        self.assertEqual(challenges.nudge_ending(), 0)
        n = Notification.objects.get(recipient=self.me, kind='challenge')
        self.assertTrue(n.text.startswith('52 miles to go on Ride 500 miles. You’re at 89% with'))

    def test_days_per_week(self):
        ch = self.challenge(title='Ride 4 days a week', kind='days_per_week', target=4, featured=False)
        ChallengeEntry.objects.create(challenge=ch, user=self.me)
        self.act(self.me)
        c = self.client_for(self.me).get('/api/performance/challenges/').data['running'][0]
        self.assertEqual(c['progress_line'], '1 / 4 days')


class TrainingTests(Base):
    def test_week_summary_consistency_and_records(self):
        self.act(self.me, distance=20000)
        Activity.objects.filter(user=self.me).update(moving_time=3600, elevation_gain=100,
                                                     best_efforts={'10 mi': 1700})
        d = self.client_for(self.me).get('/api/performance/training/?range=week').data
        s = d['summary']
        self.assertEqual(len(s['bars']), 7)
        self.assertEqual(s['total'], 12.4)
        self.assertTrue(any(b['today'] for b in s['bars']))
        self.assertEqual(d['consistency']['streak_weeks'], 1)
        self.assertEqual(d['consistency']['goal_line'], '1 of 4 days this week')
        self.assertTrue(d['trend']['locked'])  # Plus
        labels = [r['label'] for r in d['records']]
        self.assertEqual(labels, ['Longest Ride', 'Fastest 10 mi', 'Biggest Climb'])
        for rng in ('month', 'year', 'all'):
            self.assertEqual(self.client_for(self.me).get(f'/api/performance/training/?range={rng}').status_code, 200)
        self.me.plan = 'plus'
        self.me.save()
        d = self.client_for(self.me).get('/api/performance/training/?range=week').data
        self.assertEqual(len(d['trend']['hours']), 12)

    def test_best_efforts_window(self):
        t0 = 1_700_000_000_000
        pts = [(40 + i * 0.0009, -73.97, None, t0 + i * 20_000) for i in range(200)]  # 100 m every 20 s
        best = matching.best_efforts('ride', pts)
        self.assertAlmostEqual(best['10 mi'], 161 * 20, delta=40)
