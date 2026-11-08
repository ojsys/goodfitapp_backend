"""Phase 8: A Good Match. Opt-in visibility, one profile at a time, the
match lock, moving on with the 9:00 AM cooldown, the private match chat,
Romantic off, blocks and reports."""

import datetime as dt
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.chats.models import ChatMessage
from apps.events.models import Event
from apps.notifications.models import Notification
from apps.safety.models import Report
from apps.social.tests import member

from . import services as svc
from .models import Decision, Match, MatchProfile


def romantic(email, name, gender, show_me='everyone', lat=40.67, lng=-73.97, **kw):
    u = member(email, name, interests=kw.pop('interests', ['cycling', 'yoga']), timezone='America/New_York', **kw)
    u.intents = ['community', 'romantic']
    u.approx_lat, u.approx_lng = lat, lng
    u.save()
    MatchProfile.objects.create(user=u, gender=gender, show_me=show_me,
                                prompts=[{'q': 'My ideal Sunday', 'a': 'A long ride, then dumplings.'}])
    return u


class Base(TestCase):
    def setUp(self):
        self.shari = romantic('shari@example.com', 'Shari Brown', 'woman', 'men')
        self.theo = romantic('theo@example.com', 'Theo Owens', 'man', 'women')
        self.camille = romantic('camille@example.com', 'Camille Laurent', 'woman', 'men')
        self.plain = member('plain@example.com', 'Alex Rivera')  # not opted in

    def c(self, user):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
        return c

    def state(self, user):
        r = self.c(user).get('/api/match/')
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def decide(self, user, other, action='like', **kw):
        return self.c(user).post('/api/match/decide/', dict(user=other.id, action=action, **kw), format='json')

    def lock(self):
        self.decide(self.theo, self.shari)
        r = self.decide(self.shari, self.theo)
        self.assertTrue(r.data['matched'])
        return Match.objects.get()


class BrowseTests(Base):
    def test_opt_in_only_and_preferences_both_ways(self):
        self.assertEqual(self.state(self.plain)['mode'], 'off')
        self.assertEqual(self.c(self.plain).post('/api/match/decide/', {'user': self.shari.id, 'action': 'like'}
                                                 ).status_code, 403)
        s = self.state(self.shari)
        self.assertEqual(s['mode'], 'browse')
        card = s['browse']['card']
        # Shari wants men: only Theo. Camille (a woman) and Alex (not opted in) never show.
        self.assertEqual(card['person']['id'], self.theo.id)
        self.assertEqual(card['age'], self.theo.age)
        self.assertIn('Cycling', card['shared'])
        self.assertEqual(card['prompts'][0]['q'], 'My ideal Sunday')
        self.assertTrue(card['meta'].endswith('mi away'))
        ids = [u.id for u, _, _ in svc.candidates(self.theo)]
        self.assertEqual(ids, [self.shari.id, self.camille.id] if ids[0] == self.shari.id else ids)
        self.assertNotIn(self.plain.id, ids)

    def test_age_and_distance_preferences(self):
        p = MatchProfile.of(self.shari)
        p.age_min, p.age_max = 40, 60
        p.save()
        self.assertIsNone(self.state(self.shari)['browse']['card'])
        p.age_min, p.age_max, p.max_miles = 21, 60, 1
        p.save()
        self.theo.approx_lat = 40.75
        self.theo.save()
        self.assertIsNone(self.state(self.shari)['browse']['card'])

    def test_pass_moves_on_and_daily_batch(self):
        r = self.decide(self.shari, self.theo, 'pass')
        self.assertFalse(r.data['matched'])
        self.assertIsNone(r.data['browse']['card'])
        # Passing again on someone already decided is refused.
        self.assertEqual(self.decide(self.shari, self.theo).status_code, 404)
        for i in range(svc.DAILY):
            u = romantic(f'm{i}@example.com', f'Sam{i} Lee', 'man')
            Decision.objects.create(actor=self.camille, target=u, action='pass')
        s = self.state(self.camille)
        self.assertEqual(s['mode'], 'browse')
        self.assertIsNone(s['browse']['card'])  # "That's everyone for today"
        self.assertEqual(self.decide(self.camille, self.theo).status_code, 409)

    def test_not_interested_and_block_hide_profiles(self):
        self.c(self.shari).post(f'/api/safety/hide/person/{self.theo.id}/')
        self.assertIsNone(self.state(self.shari)['browse']['card'])
        self.c(self.shari).delete(f'/api/safety/hide/person/{self.theo.id}/')
        self.assertEqual(self.state(self.shari)['browse']['card']['person']['id'], self.theo.id)
        self.c(self.theo).post(f'/api/safety/blocks/{self.shari.id}/')
        self.assertIsNone(self.state(self.shari)['browse']['card'])

    def test_romantic_off_hides_immediately(self):
        self.c(self.theo).patch('/api/auth/settings/', {'match_visible': False}, format='json')
        self.theo.refresh_from_db()
        self.assertEqual(self.state(self.theo)['mode'], 'off')
        self.assertIsNone(self.state(self.shari)['browse']['card'])

    def test_first_date_idea_is_an_open_event_never_featured(self):
        soon = timezone.now() + dt.timedelta(days=2)
        Event.objects.create(title='Sponsored Spin', host=self.plain, start_time=soon, kind='featured',
                             activity_type='ride', latitude=40.67, longitude=-73.97)
        Event.objects.create(title='Club only', host=self.plain, start_time=soon, who_can_join='club',
                             activity_type='ride', latitude=40.67, longitude=-73.97)
        Event.objects.create(title='Sunset Yoga in the Park', host=self.plain, start_time=soon,
                             activity_type='yoga', location_name='Flow Studio', latitude=40.671, longitude=-73.97)
        idea = self.state(self.shari)['browse']['card']['idea']
        self.assertEqual(idea['title'], 'Sunset Yoga in the Park')
        self.assertIn('You’re both near Flow Studio', idea['line'])


class MatchTests(Base):
    def test_like_back_locks_the_match_and_opens_a_private_chat(self):
        r = self.decide(self.theo, self.shari, prompt='My ideal Sunday', note='Dumplings where?')
        self.assertFalse(r.data['matched'])
        self.assertFalse(Notification.objects.filter(recipient=self.shari).exists())  # likes stay private
        m = self.lock()
        self.assertEqual(m.state, 'locked')
        s = self.state(self.shari)
        self.assertEqual(s['mode'], 'locked')
        self.assertEqual(s['match']['person']['id'], self.theo.id)
        self.assertEqual(s['match']['matched'], 'Matched today')
        self.assertEqual(self.state(self.theo)['mode'], 'locked')
        self.assertTrue(Notification.objects.filter(recipient=self.theo, kind='match').exists())
        # Theo's prompt reply opens the chat.
        first = ChatMessage.objects.filter(chat=m.chat).first()
        self.assertEqual((first.sender_id, first.attachment, first.body), (self.theo.id, 'prompt', 'Dumplings where?'))
        # Locked: no one new, for either of them, and they leave everyone's browse.
        self.assertNotIn(self.theo.id, [u.id for u, _, _ in svc.candidates(self.camille)])
        self.assertEqual(self.decide(self.shari, self.camille).status_code, 409)

    def test_match_chat_in_inbox_private_text_only(self):
        m = self.lock()
        inbox = self.c(self.shari).get('/api/chats/').data
        self.assertEqual([r['id'] for r in inbox['match']], [m.chat_id])
        self.assertEqual(inbox['match'][0]['age'], self.theo.age)
        self.assertNotIn(m.chat_id, [r['id'] for r in inbox['direct']])
        head = self.c(self.shari).get(f'/api/chats/{m.chat_id}/').data
        self.assertTrue(head['private'])
        self.assertEqual(head['subtitle'], 'Matched today')
        ok = self.c(self.shari).post(f'/api/chats/{m.chat_id}/messages/', {'body': 'Hi Theo!'}, format='json')
        self.assertEqual(ok.status_code, 201)
        no = self.c(self.shari).post(f'/api/chats/{m.chat_id}/messages/',
                                     {'attachment': 'location', 'latitude': 1, 'longitude': 2}, format='json')
        self.assertEqual(no.status_code, 400)
        self.assertTrue(self.state(self.shari)['match']['steps']['said_hi'])
        # Not in the Community hub's Messages, and not a share target.
        hub = self.c(self.shari).get('/api/social/community/').data
        self.assertNotIn(m.chat_id, [x['id'] for x in hub['messages']])

    def test_suggest_meetup_met_keep_and_open_up(self):
        e = Event.objects.create(title='Sunset Yoga in the Park', host=self.plain, activity_type='yoga',
                                 start_time=timezone.now() + dt.timedelta(days=3), location_name='Flow Studio')
        m = self.lock()
        s = self.c(self.shari).post(f'/api/match/{m.id}/suggest/', {'event': e.id}, format='json').data
        self.assertTrue(s['match']['suggested'] and s['match']['suggested_by_me'])
        self.assertTrue(s['match']['steps']['planned'])
        card = ChatMessage.objects.get(chat=m.chat, attachment='meetup')
        self.assertEqual(card.share['title'], 'Sunset Yoga in the Park')
        self.assertTrue(self.state(self.theo)['match']['suggested'])
        # Only the suggester can take it back.
        self.assertEqual(self.c(self.theo).delete(f'/api/match/{m.id}/suggest/').status_code, 403)
        s = self.c(self.shari).post(f'/api/match/{m.id}/met/').data
        self.assertEqual(s['mode'], 'met')
        self.assertEqual(self.state(self.theo)['mode'], 'locked')  # Theo hasn't said yet
        s = self.c(self.shari).post(f'/api/match/{m.id}/keep/').data
        self.assertEqual(s['mode'], 'locked')
        self.assertTrue(s['match']['steps']['met'])
        s = self.c(self.theo).post(f'/api/match/{m.id}/met/').data
        s = self.c(self.theo).post(f'/api/match/{m.id}/open/').data
        self.assertEqual(s['mode'], 'browse')
        # Shari isn't told and stays focused; Theo can browse again.
        self.assertEqual(self.state(self.shari)['mode'], 'locked')
        self.assertFalse(Notification.objects.filter(recipient=self.shari, kind='match').exclude(
            parts__0__0='You and ').exists())

    def test_move_on_cooldown_until_nine_and_kind_note(self):
        m = self.lock()
        # 8 PM yesterday in New York.
        ny = svc.safe_zone('America/New_York')
        at = (timezone.now().astimezone(ny) - dt.timedelta(days=1)).replace(hour=20, minute=0, second=0)
        with mock.patch('django.utils.timezone.now', return_value=at):
            s = self.c(self.shari).post(f'/api/match/{m.id}/move-on/').data
        self.assertEqual(s['mode'], 'cool')
        p = MatchProfile.of(self.shari)
        self.assertEqual(p.cooldown_until.astimezone(ny).strftime('%d %H:%M'),
                         (at + dt.timedelta(days=1)).strftime('%d 09:00'))
        m.refresh_from_db()
        self.assertEqual(m.state, 'ended')
        self.assertTrue(m.chat.is_closed)
        note = Notification.objects.filter(recipient=self.theo, kind='match').order_by('-id').first()
        self.assertIn('has ended', note.text)
        self.assertIsNone(note.actor)  # no details, not even who to tap through to
        # Theo can browse right away; Shari waits.
        self.assertEqual(self.state(self.theo)['mode'], 'browse')
        r = self.c(self.shari).post(f'/api/chats/{m.chat_id}/messages/', {'body': 'Hi'}, format='json')
        self.assertEqual((r.status_code, r.data['code']), (409, 'closed'))
        self.assertNotIn(m.chat_id, [r['id'] for r in self.c(self.theo).get('/api/chats/').data['match']])
        with mock.patch('django.utils.timezone.now', return_value=at + dt.timedelta(hours=14)):
            self.assertEqual(svc.state(self.shari)['mode'], 'browse')

    def test_romantic_off_pauses_the_match(self):
        m = self.lock()
        self.c(self.theo).patch('/api/auth/settings/', {'match_visible': False}, format='json')
        s = self.state(self.shari)
        self.assertTrue(s['match']['on_hold'])
        r = self.c(self.shari).post(f'/api/chats/{m.chat_id}/messages/', {'body': 'Hi'}, format='json')
        self.assertEqual(r.status_code, 409)
        # Theo doesn't see the chat while Romantic is off.
        self.assertEqual(self.c(self.theo).get(f'/api/chats/{m.chat_id}/').status_code, 404)
        # Moving on from a match on hold doesn't start a cooldown.
        self.assertEqual(self.c(self.shari).post(f'/api/match/{m.id}/move-on/').data['mode'], 'browse')

    def test_block_ends_the_match_and_report_keeps_the_chat(self):
        m = self.lock()
        self.c(self.theo).post(f'/api/chats/{m.chat_id}/messages/', {'body': 'Hey'}, format='json')
        r = self.c(self.shari).post('/api/safety/reports/', {
            'target_kind': 'member', 'target_id': self.theo.id, 'reason': 'spam', 'context': 'match_chat',
            'block': True}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        rep = Report.objects.get()
        self.assertEqual(rep.context, 'Your match in A Good Match')
        self.assertIn('Hey', rep.snapshot)
        self.assertIn('My ideal Sunday', rep.snapshot)
        m.refresh_from_db()
        self.assertEqual(m.state, 'ended')
        self.assertEqual(self.state(self.shari)['mode'], 'browse')  # no cooldown after a block

    def test_profile_and_age_only_here(self):
        r = self.c(self.shari).patch('/api/match/profile/', {
            'prompts': [{'q': 'Typical Saturday', 'a': 'Run Club, then breakfast.'}], 'pace_note': 'Easy, chatty',
            'age_min': 25, 'age_max': 40, 'show_me': 'everyone'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['prompts'][0]['q'], 'Typical Saturday')
        bad = self.c(self.shari).patch('/api/match/profile/', {'prompts': [{'q': 'Made up', 'a': 'x'}]},
                                       format='json')
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.c(self.shari).patch('/api/match/profile/', {'age_min': 18}, format='json')
                         .status_code, 400)
        # Age and opt-in never show on a regular profile.
        prof = self.c(self.theo).get(f'/api/social/people/{self.shari.id}/').data
        self.assertNotIn('age', str(prof.keys()))
        self.assertNotIn('match', prof)
        # You: the count of new profiles today.
        me = self.c(self.shari).get('/api/social/me/profile/').data
        self.assertEqual(me['match']['new_today'], 1)
