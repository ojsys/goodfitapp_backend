"""Phase 6: notifications, settings, push devices, reminders."""

import datetime as dt
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.events.models import Event, EventRSVP
from apps.safety.models import Block, Report
from apps.social.models import Announcement, Club, ClubMembership, Comment, Follow, Prop, RideInvite, Wave
from apps.social.tests import Base, member

from .models import Device, Notification, NotificationSettings


def event(host, **kw):
    return Event.objects.create(title=kw.pop('title', 'Sunday Social Ride'), description='', host=host,
                                host_name='GoodCo', vibe='Social',
                                start_time=kw.pop('start_time', timezone.now() + dt.timedelta(days=3)),
                                location_name='Grand Army Plaza', location_address='x', **kw)


class NotificationTests(Base):
    def texts(self, user):
        return [n.text for n in Notification.objects.filter(recipient=user)]

    def test_props_group_into_one_row(self):
        act = self.act(self.me, title='Wednesday evening ride')
        sasha = member('sasha@example.com', 'Sasha Kim')
        for u in (self.friend, self.stranger, sasha):
            Prop.objects.create(user=u, activity=act)
        rows = Notification.objects.filter(recipient=self.me, kind='props')
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows[0].text, 'Sasha, Alex and 1 other gave props to your Wednesday evening ride.')
        self.assertEqual(rows[0].link, f'/activity/{act.id}')
        # Once read, the next prop starts a new row.
        rows.update(read_at=timezone.now())
        Prop.objects.filter(user=sasha).delete()
        Prop.objects.create(user=sasha, activity=act)
        self.assertEqual(Notification.objects.filter(recipient=self.me, kind='props').count(), 2)

    def test_comment_follow_wave_invite(self):
        act = self.act(self.me)
        Comment.objects.create(author=self.friend, activity=act, text='4 seconds off the PR on Park Drive.')
        Follow.objects.create(follower=self.stranger, followee=self.me)
        Wave.objects.create(sender=self.stranger, recipient=self.me)
        e = event(self.friend, title='Greenpoint Shakeout')
        RideInvite.objects.create(sender=self.friend, recipient=self.me, event=e)
        t = self.texts(self.me)
        self.assertIn('Marvel commented: “4 seconds off the PR on Park Drive.”', t)
        self.assertIn('Alex started following you.', t)
        self.assertIn('Alex waved at you. Say hi back?', t)
        self.assertTrue(any(x.startswith('Marvel invited you to the Greenpoint Shakeout on ') for x in t))
        # Not about yourself.
        Comment.objects.create(author=self.me, activity=act, text='thanks!')
        self.assertFalse(any('Shari commented' in x for x in self.texts(self.me)))

    def test_blocked_and_turned_off_kinds_are_skipped(self):
        act = self.act(self.me)
        Block.objects.create(blocker=self.me, blocked=self.stranger)
        s = NotificationSettings.of(self.me)
        s.props_comments = False
        s.save()
        Comment.objects.create(author=self.friend, activity=act, text='nice')
        Follow.objects.create(follower=self.stranger, followee=self.me)
        self.assertEqual(self.texts(self.me), [])
        # Safety notes always come through.
        r = Report.objects.create(reporter=self.me, target_kind='member', target_user=self.friend,
                                  target_id=self.friend.id, reason='fake')
        from apps.safety import moderation
        moderation.decide(r, 'no_violation', self.stranger)
        self.assertEqual(self.texts(self.me), ['We reviewed your report and have an update for you in Your reports.'])

    def test_ride_change_and_announcement(self):
        e = event(self.friend)
        EventRSVP.objects.create(event=e, user=self.me, status='going')
        e.location_name = 'Prospect Park, Grand Army entrance'
        e.save()
        self.assertIn('Sunday Social Ride · Now meeting at Prospect Park, Grand Army entrance.', self.texts(self.me))
        club = Club.objects.create(name='GoodCo Bike Club', initials='GC')
        ClubMembership.objects.create(club=club, user=self.me)
        Announcement.objects.create(club=club, author=self.friend, text='Lights on', pinned=True)
        self.assertIn('Marvel pinned an announcement in GoodCo Bike Club.', self.texts(self.me))

    def test_list_sections_read_all_and_header_count(self):
        Follow.objects.create(follower=self.stranger, followee=self.me)
        old = Notification.objects.create(recipient=self.me, kind='follow', parts=[['Old', True]],
                                          read_at=timezone.now())
        Notification.objects.filter(pk=old.pk).update(updated_at=timezone.now() - dt.timedelta(days=3))
        c = self.client_for(self.me)
        d = c.get('/api/notifications/').data
        self.assertEqual([s['title'] for s in d['sections']], ['New', 'Earlier This Week'])
        first = d['sections'][0]['items'][0]
        self.assertEqual((first['parts'][0], first['person']['first_name'], first['unread']),
                         (['Alex', True], 'Alex', True))
        self.assertEqual(c.get('/api/social/home/').data['counts']['notifications'], 1)
        c.post('/api/notifications/read-all/')
        self.assertEqual(c.get('/api/notifications/unread/').data['unread'], 0)

    def test_settings_and_devices(self):
        c = self.client_for(self.me)
        d = c.patch('/api/notifications/settings/', {'messages': False}, format='json').data
        self.assertFalse(d['messages'])
        self.assertFalse(d['push_available'])
        r = c.post('/api/notifications/devices/', {'token': 'abc', 'platform': 'ios'}, format='json')
        self.assertEqual(r.status_code, 200)
        c.post('/api/notifications/devices/', {'token': 'abc', 'platform': 'ios'}, format='json')
        self.assertEqual(Device.objects.count(), 1)
        c.delete('/api/notifications/devices/', {'token': 'abc'}, format='json')
        self.assertFalse(Device.objects.exists())

    @override_settings(FCM_PROJECT_ID='p', FCM_CREDENTIALS_JSON='{}')
    def test_push_goes_to_devices_after_commit(self):
        Device.objects.create(user=self.me, token='t1', platform='ios')
        with mock.patch('apps.notifications.push._send_now') as send, \
                self.captureOnCommitCallbacks(execute=True):
            Follow.objects.create(follower=self.stranger, followee=self.me)
        import time
        time.sleep(0.2)  # the thread runs the send
        send.assert_called_once()
        self.assertEqual(send.call_args[0][0], ['t1'])
        self.assertEqual(send.call_args[0][2], 'Alex started following you.')

    def test_day_before_reminder_once(self):
        e = event(self.friend, title='Halloween Glow Walk', start_time=timezone.now() + dt.timedelta(hours=24))
        for u in (self.me, self.friend, self.stranger):
            EventRSVP.objects.create(event=e, user=u, status='going')
        call_command('send_reminders', stdout=StringIO())
        call_command('send_reminders', stdout=StringIO())
        rows = Notification.objects.filter(recipient=self.me, kind='ride_reminder')
        self.assertEqual(rows.count(), 1)
        self.assertIn('3 people are going.', rows[0].text)
