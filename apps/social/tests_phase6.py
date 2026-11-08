"""Phase 6: profiles, account and settings, sharing and public pages."""

import json
from urllib.parse import urlparse

from apps.activities.models import Activity
from apps.chats.models import ChatMessage
from apps.safety.models import Block
from apps.users.models import User

from .models import Club, ClubMembership, Follow
from .tests import Base


class ProfileTests(Base):
    def test_my_profile(self):
        self.act(self.me, distance=20000)
        Follow.objects.create(follower=self.friend, followee=self.me)
        d = self.client_for(self.me).get('/api/social/me/profile/').data
        self.assertEqual((d['following'], d['followers']), (1, 1))
        self.assertEqual(d['season']['activities'], 1)
        self.assertEqual(d['training']['streak_weeks'], 1)
        self.assertTrue(d['share_url'].endswith(f'/u/{self.me.id}'))

    def test_someone_elses_profile_respects_privacy_and_blocks(self):
        self.act(self.stranger, vis='everyone', title='Public loop')
        self.act(self.stranger, vis='followers', title='Followers loop')
        c = self.client_for(self.me)
        d = c.get(f'/api/social/people/{self.stranger.id}/').data
        self.assertEqual([a['title'] for a in d['recent']], ['Public loop'])
        self.assertFalse(d['is_following'])
        Block.objects.create(blocker=self.stranger, blocked=self.me)
        self.assertEqual(c.get(f'/api/social/people/{self.stranger.id}/').status_code, 404)

    def test_follow_lists(self):
        d = self.client_for(self.friend).get(f'/api/social/people/{self.friend.id}/followers/').data
        self.assertEqual([p['first_name'] for p in d['items']], ['Shari'])


class AccountTests(Base):
    def test_edit_profile(self):
        c = self.client_for(self.me)
        r = c.patch('/api/auth/me/', {'name': 'Shari  Brown-Lee', 'neighborhood': 'Fort Greene',
                                      'interests': ['cycling', 'yoga', 'walking'], 'units': 'km',
                                      'bio': 'Rides at dawn.'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.me.refresh_from_db()
        self.assertEqual((self.me.first_name, self.me.last_name, self.me.units), ('Shari', 'Brown-Lee', 'km'))
        r = c.patch('/api/auth/me/', {'interests': ['a', 'b', 'c', 'd']}, format='json')
        self.assertEqual(r.data['code'], 'interests')
        r = c.patch('/api/auth/me/', {'bio': 'x' * 151}, format='json')
        self.assertEqual(r.data['code'], 'bio')

    def test_settings(self):
        c = self.client_for(self.me)
        d = c.get('/api/auth/settings/').data
        self.assertTrue(d['privacy_zones_on'])
        d = c.patch('/api/auth/settings/', {'privacy_zones_on': False, 'default_visibility': 'club',
                                            'match_visible': True, 'notifications': {'messages': False}},
                    format='json').data
        self.assertEqual((d['privacy_zones_on'], d['default_visibility'], d['match']['visible'],
                          d['notifications']['messages']), (False, 'club', True, False))
        self.assertEqual(c.patch('/api/auth/settings/', {'default_visibility': 'world'}, format='json').status_code,
                         400)

    def test_email_change_needs_password(self):
        c = self.client_for(self.me)
        self.assertEqual(c.post('/api/auth/email/', {'email': 'new@example.com', 'password': 'nope'},
                                format='json').status_code, 403)
        self.assertEqual(c.post('/api/auth/email/', {'email': 'friend@example.com', 'password': 'goodfit123'},
                                format='json').data['code'], 'taken')
        r = c.post('/api/auth/email/', {'email': 'New@Example.com', 'password': 'goodfit123'}, format='json')
        self.assertEqual(r.data['email'], 'new@example.com')

    def test_export_and_delete(self):
        self.act(self.me, title='Mine')
        c = self.client_for(self.me)
        r = c.get('/api/auth/export/')
        self.assertIn('attachment;', r['Content-Disposition'])
        data = json.loads(r.content)
        self.assertEqual([a['title'] for a in data['activities']], ['Mine'])
        self.assertEqual(c.post('/api/auth/delete/', {'password': 'wrong'}, format='json').status_code, 403)
        self.assertEqual(c.post('/api/auth/delete/', {'password': 'goodfit123'}, format='json').status_code, 204)
        self.assertFalse(User.objects.filter(email='me@example.com').exists())
        self.assertFalse(Activity.objects.filter(title='Mine').exists())


class ShareTests(Base):
    def test_activity_card_public_toggle_and_page(self):
        a = self.act(self.me, title='Wednesday evening ride', distance=20278)
        c = self.client_for(self.me)
        d = c.get(f'/api/share/activity/{a.id}/').data
        self.assertEqual((d['heading'], d['vis'], d['can_public']),
                         ('Share this ride', 'Only your followers can open this link', True))
        self.assertTrue(d['url'].endswith(f'/a/{a.id}'))
        self.assertEqual(d['story']['stats'][0], {'label': 'Distance', 'value': '12.6 mi'})
        page = self.client.get(f'/a/{a.id}')
        self.assertContains(page, 'Shared with followers')
        self.assertNotContains(page, 'Wednesday evening ride')
        d = c.patch(f'/api/share/activity/{a.id}/', {'public': True}, format='json').data
        self.assertEqual(d['vis'], 'Anyone with the link can open this')
        page = self.client.get(f'/a/{a.id}')
        self.assertContains(page, 'Wednesday evening ride')
        self.assertContains(page, 'property="og:title"')
        # Others can't flip it, and can't share what they can't see.
        self.assertEqual(self.client_for(self.friend).patch(f'/api/share/activity/{a.id}/', {'public': False},
                                                            format='json').status_code, 404)
        private = self.act(self.me, vis='me')
        self.assertEqual(self.client_for(self.friend).get(f'/api/share/activity/{private.id}/').status_code, 404)

    def test_send_to_people(self):
        club = Club.objects.create(name='GoodCo Bike Club', initials='GC')
        ClubMembership.objects.create(club=club, user=self.me)
        c = self.client_for(self.me)
        recips = c.get('/api/share/recipients/?kind=club').data
        self.assertIn(self.friend.id, [p['id'] for p in recips['people']])
        r = c.post('/api/share/send/', {'kind': 'club_invite', 'id': club.id, 'users': [self.friend.id],
                                        'note': 'Come ride with us'}, format='json')
        self.assertEqual(r.data, {'sent': 1})
        m = ChatMessage.objects.get()
        self.assertEqual((m.attachment, m.body, m.share['title']), ('share', 'Come ride with us', 'GoodCo Bike Club'))
        page = self.client.get(urlparse(m.share['url']).path)
        self.assertContains(page, 'Shari invited you')

    def test_profile_and_club_pages(self):
        self.assertContains(self.client.get(f'/u/{self.me.id}'), 'Shari Brown')
        club = Club.objects.create(name='GoodCo Bike Club', initials='GC')
        self.assertContains(self.client.get(f'/c/{club.id}'), 'GoodCo Bike Club')
        self.assertEqual(self.client.get('/join/1-2-deadbeef').status_code, 404)
