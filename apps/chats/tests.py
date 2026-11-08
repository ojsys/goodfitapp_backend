"""Phase 4: ride chats, DMs, slow mode, moderation, reports and blocks."""

import datetime as dt
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.events.models import Event, EventRSVP
from apps.safety.models import Block, Report
from apps.social.models import Club, ClubMembership, ClubTeamLog
from apps.social.tests import Base

from .models import Chat, ChatMember, ChatMessage

NO_THROTTLE = {'DEFAULT_THROTTLE_RATES': {'auth': '1000/hour', 'password_reset': '1000/hour',
                                          'messages': '10000/hour', 'reports': '1000/hour'}}


def event(host, **kw):
    return Event.objects.create(title=kw.pop('title', 'Sunday Social Ride'), description='', host=host,
                                host_name='GoodCo', vibe='Social',
                                start_time=kw.pop('start_time', timezone.now() + dt.timedelta(days=2)),
                                location_name='Grand Army Plaza', location_address='x', **kw)


class RideChatTests(Base):
    def setUp(self):
        super().setUp()
        self.club = Club.objects.create(name='GoodCo Bike Club', initials='GC')
        ClubMembership.objects.create(club=self.club, user=self.friend, role='organizer')
        self.ev = event(self.friend, club=self.club)

    def rsvp(self, user):
        return EventRSVP.objects.create(event=self.ev, user=user, status='going')

    def test_rsvp_opens_and_leaves_ride_chat(self):
        r = self.rsvp(self.me)
        chat = Chat.objects.get(event=self.ev)
        self.assertTrue(ChatMember.objects.filter(chat=chat, user=self.me).exists())
        self.assertEqual(chat.closes_at, self.ev.start_time + dt.timedelta(minutes=180) + dt.timedelta(hours=48))
        r.delete()
        self.assertFalse(ChatMember.objects.filter(chat=chat, user=self.me).exists())
        self.assertEqual(self.client_for(self.me).get(f'/api/chats/{chat.id}/').status_code, 404)

    def test_send_and_role_badges(self):
        self.rsvp(self.me)
        self.rsvp(self.friend)
        chat = Chat.objects.get(event=self.ev)
        c = self.client_for(self.friend)
        r = c.post(f'/api/chats/{chat.id}/messages/', {'body': 'Rolling at 8 sharp.'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['badge'], 'Organizer')
        got = self.client_for(self.me).get(f'/api/chats/{chat.id}/messages/').data
        self.assertEqual([m['body'] for m in got['items']], ['Rolling at 8 sharp.'])
        inbox = self.client_for(self.me).get('/api/chats/').data
        self.assertEqual(inbox['ride'][0]['unread'], 1)
        self.assertEqual(inbox['ride'][0]['preview'], 'Marvel: Rolling at 8 sharp.')
        self.client_for(self.me).post(f'/api/chats/{chat.id}/read/', {'last_id': r.data['id']}, format='json')
        self.assertEqual(self.client_for(self.me).get('/api/chats/unread/').data['unread'], 0)

    def test_read_only_48_hours_after(self):
        self.rsvp(self.me)
        chat = Chat.objects.get(event=self.ev)
        Chat.objects.filter(pk=chat.pk).update(closes_at=timezone.now() - dt.timedelta(minutes=1))
        r = self.client_for(self.me).post(f'/api/chats/{chat.id}/messages/', {'body': 'hi'}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data['code'], 'closed')

    @override_settings(REST_FRAMEWORK={**__import__('django.conf').conf.settings.REST_FRAMEWORK, **NO_THROTTLE})
    def test_slow_mode_and_spam_pause(self):
        self.rsvp(self.me)
        chat = Chat.objects.get(event=self.ev)
        c = self.client_for(self.me)
        for i in range(3):
            self.assertEqual(c.post(f'/api/chats/{chat.id}/messages/', {'body': f'm{i}'}, format='json').status_code, 201)
        r = c.post(f'/api/chats/{chat.id}/messages/', {'body': 'too fast'}, format='json')
        self.assertEqual(r.status_code, 429)
        self.assertFalse(r.data['paused'])
        until = timezone.datetime.fromisoformat(r.data['locked_until'])
        self.assertAlmostEqual((until - timezone.now()).total_seconds(), 30, delta=2)
        # Still locked.
        self.assertEqual(c.post(f'/api/chats/{chat.id}/messages/', {'body': 'x'}, format='json').status_code, 429)
        # Three locks in an hour: paused for a day.
        m = ChatMember.objects.get(chat=chat, user=self.me)
        later = timezone.now()
        for k in range(2):
            later += dt.timedelta(seconds=40)
            m.refresh_from_db()
            ChatMember.objects.filter(pk=m.pk).update(locked_until=None)
            with mock.patch('django.utils.timezone.now', return_value=later):
                for i in range(3):
                    ChatMessage.objects.create(chat=chat, sender=self.me, body='spam')
                ChatMessage.objects.filter(chat=chat, sender=self.me, created_at__gte=later).update(created_at=later)
                r = c.post(f'/api/chats/{chat.id}/messages/', {'body': 'again'}, format='json')
        self.assertEqual(r.status_code, 429)
        self.assertTrue(r.data['paused'])

    def test_client_id_dedupes_resends(self):
        self.rsvp(self.me)
        chat = Chat.objects.get(event=self.ev)
        c = self.client_for(self.me)
        a = c.post(f'/api/chats/{chat.id}/messages/', {'body': 'hi', 'client_id': 'abc'}, format='json')
        b = c.post(f'/api/chats/{chat.id}/messages/', {'body': 'hi', 'client_id': 'abc'}, format='json')
        self.assertEqual(a.data['id'], b.data['id'])
        self.assertEqual(ChatMessage.objects.count(), 1)

    def test_team_can_remove_and_it_is_logged(self):
        self.rsvp(self.me)
        self.rsvp(self.friend)
        chat = Chat.objects.get(event=self.ev)
        r = self.client_for(self.me).post(f'/api/chats/{chat.id}/messages/', {'body': 'buy my stuff'}, format='json')
        self.assertEqual(self.client_for(self.stranger).delete(f'/api/chats/messages/{r.data["id"]}/').status_code, 403)
        self.assertEqual(self.client_for(self.friend).delete(f'/api/chats/messages/{r.data["id"]}/').status_code, 204)
        got = self.client_for(self.me).get(f'/api/chats/{chat.id}/messages/').data['items'][0]
        self.assertTrue(got['removed'])
        self.assertEqual(got['body'], '')
        self.assertTrue(ClubTeamLog.objects.filter(club=self.club).exists())


class DirectAndSafetyTests(Base):
    def test_direct_chat_and_block(self):
        c = self.client_for(self.me)
        h = c.post('/api/chats/direct/', {'user': self.friend.id}, format='json').data
        again = c.post('/api/chats/direct/', {'user': self.friend.id}, format='json').data
        self.assertEqual(h['id'], again['id'])
        c.post(f'/api/chats/{h["id"]}/messages/', {'body': 'See you Saturday?'}, format='json')
        inbox = self.client_for(self.friend).get('/api/chats/').data
        self.assertEqual(inbox['direct'][0]['title'], 'Shari')
        self.assertEqual(inbox['direct'][0]['unread'], 1)
        Block.objects.create(blocker=self.friend, blocked=self.me)
        r = c.post(f'/api/chats/{h["id"]}/messages/', {'body': 'hello?'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client_for(self.friend).get('/api/chats/').data['direct'], [])

    def test_report_message_and_block(self):
        c = self.client_for(self.me)
        h = c.post('/api/chats/direct/', {'user': self.friend.id}, format='json').data
        msg = self.client_for(self.friend).post(f'/api/chats/{h["id"]}/messages/', {'body': 'rude thing'},
                                                format='json').data
        r = c.post('/api/safety/reports/', {'target_kind': 'message', 'target_id': msg['id'], 'reason': 'other'},
                   format='json')
        self.assertEqual(r.data['code'], 'details')
        r = c.post('/api/safety/reports/', {'target_kind': 'message', 'target_id': msg['id'], 'reason': 'unsafe',
                                            'block': True}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['urgent'])
        rep = Report.objects.get()
        self.assertEqual(rep.target_user, self.friend)
        self.assertIn('> Marvel', rep.snapshot)
        self.assertIn('rude thing', rep.snapshot)
        self.assertEqual(rep.context, 'Message in Marvel')
        self.assertTrue(Block.objects.filter(blocker=self.me, blocked=self.friend).exists())
        # Blocked people's messages disappear for the blocker.
        self.assertEqual(c.get(f'/api/chats/{h["id"]}/messages/').data['items'], [])

    def test_location_and_live_updates(self):
        c = self.client_for(self.me)
        h = c.post('/api/chats/direct/', {'user': self.friend.id}, format='json').data
        r = c.post(f'/api/chats/{h["id"]}/messages/', {'attachment': 'location', 'latitude': 40.67,
                                                       'longitude': -73.97, 'live_minutes': 15}, format='json')
        self.assertTrue(r.data['location']['live'])
        c.patch(f'/api/chats/messages/{r.data["id"]}/location/', {'latitude': 40.68, 'longitude': -73.96}, format='json')
        c.patch(f'/api/chats/messages/{r.data["id"]}/location/', {'stop': True}, format='json')
        got = self.client_for(self.friend).get(f'/api/chats/{h["id"]}/messages/').data['items'][0]
        self.assertEqual(got['location']['latitude'], 40.68)
        self.assertFalse(got['location']['live'])
        self.assertEqual(c.post(f'/api/chats/{h["id"]}/messages/', {'attachment': 'location', 'latitude': 1,
                                                                    'longitude': 1, 'live_minutes': 600},
                                format='json').status_code, 400)
