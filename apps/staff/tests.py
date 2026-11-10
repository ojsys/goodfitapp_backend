from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase

from apps.safety.models import Report, SupportMessage

from . import roles

User = get_user_model()


class StaffDashboardTests(TestCase):
    def setUp(self):
        roles.sync()
        self.admin = User.objects.create_user(email='admin@test.agoodfit.app', password='pw-admin-123',
                                              first_name='Ada', is_staff=True, is_superuser=True)
        self.staff = User.objects.create_user(email='staff@test.agoodfit.app', password='pw-staff-123',
                                              first_name='Sam', is_staff=True)
        self.staff.groups.add(Group.objects.get(name='Staff'))
        self.member = User.objects.create_user(email='m@test.agoodfit.app', password='pw-member-123',
                                               first_name='Mo')

    def tearDown(self):
        cache.clear()

    def as_(self, u):
        self.client.force_login(u)

    def test_login_is_staff_only(self):
        r = self.client.post('/api/staff/login/', {'email': 'm@test.agoodfit.app', 'password': 'pw-member-123'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 403)
        r = self.client.post('/api/staff/login/', {'email': 'staff@test.agoodfit.app', 'password': 'pw-staff-123'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['user']['role'], 'staff')

    def test_members_get_nothing(self):
        self.as_(self.member)
        self.assertEqual(self.client.get('/api/staff/overview/').status_code, 403)
        self.assertEqual(self.client.get('/api/staff/models/').status_code, 403)

    def test_overview_and_models(self):
        self.as_(self.staff)
        r = self.client.get('/api/staff/overview/').json()
        self.assertEqual(r['stats'][0]['k'], 'Members')
        self.assertEqual(len(r['signups']), 30)
        apps = {g['app']: g for g in self.client.get('/api/staff/models/').json()['apps']}
        self.assertIn('users', apps)
        user_model = next(m for m in apps['users']['models'] if m['key'] == 'users.user')
        self.assertTrue(user_model['perms']['view'])
        self.assertFalse(user_model['perms']['delete'])

    def test_secrets_never_sent_and_private_text_admin_only(self):
        from apps.messaging.models import Conversation, Message
        c = Conversation.objects.create(participant1=self.member, participant2=self.admin)
        msg = Message.objects.create(conversation=c, sender=self.member, text='meet at 6?')
        self.as_(self.staff)
        d = self.client.get(f'/api/staff/models/users.user/{self.member.pk}/').json()
        pw = next(f for f in d['fields'] if f['name'] == 'password')
        self.assertEqual(pw['value'], {'hidden': 'secret'})
        self.assertNotIn('pbkdf2', str(d))
        d = self.client.get(f'/api/staff/models/messaging.message/{msg.pk}/').json()
        self.assertEqual(next(f for f in d['fields'] if f['name'] == 'text')['value'], {'hidden': 'private'})
        self.as_(self.admin)
        d = self.client.get(f'/api/staff/models/messaging.message/{msg.pk}/').json()
        self.assertEqual(next(f for f in d['fields'] if f['name'] == 'text')['value'], 'meet at 6?')

    def test_list_search_filter(self):
        self.as_(self.admin)
        r = self.client.get('/api/staff/models/users.user/?q=m@test').json()
        self.assertEqual(r['total'], 1)
        r = self.client.get('/api/staff/models/users.user/?f_is_staff=true').json()
        self.assertEqual(r['total'], 2)

    def test_edit_is_logged_and_follows_permissions(self):
        self.as_(self.staff)
        # Staff can view support messages' model but not edit events.
        from apps.events.models import Event
        self.assertEqual(self.client.patch('/api/staff/models/events.event/1/', {'title': 'x'},
                                           content_type='application/json').status_code, 403)
        seen = self.member.last_seen
        r = self.client.patch(f'/api/staff/models/users.user/{self.member.pk}/', {'first_name': 'Morgan'},
                              content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.member.refresh_from_db()
        self.assertEqual(self.member.first_name, 'Morgan')
        self.assertEqual(self.member.last_seen, seen)  # an edit isn't activity
        self.assertTrue(LogEntry.objects.filter(object_id=str(self.member.pk), user=self.staff).exists())
        # Staff can't hand out staff rights.
        r = self.client.patch(f'/api/staff/models/users.user/{self.member.pk}/', {'is_staff': True},
                              content_type='application/json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Event.objects.filter(title='x').exists())

    def test_admin_delete_with_preview(self):
        s = SupportMessage.objects.create(user=self.member, topic='question', text='hi')
        self.as_(self.admin)
        d = self.client.get(f'/api/staff/models/safety.supportmessage/{s.pk}/?delete_preview=1').json()
        self.assertEqual(d['delete_preview'][0]['count'], 1)
        self.assertEqual(self.client.delete(f'/api/staff/models/safety.supportmessage/{s.pk}/').status_code, 204)
        self.assertFalse(SupportMessage.objects.filter(pk=s.pk).exists())

    def test_report_queue_and_decision(self):
        r = Report.objects.create(reporter=self.admin, target_kind='member', target_user=self.member,
                                  reason='unsafe', priority=Report.PRIORITY_UNSAFE, context='Profile')
        self.as_(self.staff)
        q = self.client.get('/api/staff/reports/').json()
        self.assertEqual(q['items'][0]['id'], r.id)
        res = self.client.post(f'/api/staff/reports/{r.id}/decide/', {'decision': 'suspend'},
                               content_type='application/json')
        self.assertEqual(res.status_code, 200, res.content)
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        r.refresh_from_db()
        self.assertEqual(r.status, 'resolved')
        # Reinstate from the member page.
        res = self.client.post(f'/api/staff/members/{self.member.pk}/reinstate/', {}, content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)

    def test_support_handled(self):
        s = SupportMessage.objects.create(user=self.member, topic='safety', text='someone followed me')
        self.as_(self.staff)
        self.assertEqual(self.client.get('/api/staff/support/').json()['items'][0]['id'], s.id)
        self.client.post(f'/api/staff/support/{s.id}/', {'handled': True}, content_type='application/json')
        s.refresh_from_db()
        self.assertTrue(s.handled)

    def test_team_roles(self):
        self.as_(self.staff)
        self.assertEqual(self.client.post('/api/staff/team/', {'email': 'm@test.agoodfit.app'},
                                          content_type='application/json').status_code, 403)
        self.as_(self.admin)
        r = self.client.post('/api/staff/team/', {'email': 'm@test.agoodfit.app', 'role': 'staff'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 201)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_staff)
        self.assertTrue(self.member.groups.filter(name='Staff').exists())
        # The last admin can't be demoted, and nobody changes their own role.
        r = self.client.patch(f'/api/staff/team/{self.admin.pk}/', {'role': 'staff'}, content_type='application/json')
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(f'/api/staff/team/{self.member.pk}/', {'role': None}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_staff)

    def test_every_model_lists_and_opens(self):
        """The generic browser must not crash on any model."""
        self.as_(self.admin)
        for g in self.client.get('/api/staff/models/').json()['apps']:
            for m in g['models']:
                r = self.client.get(f'/api/staff/models/{m["key"]}/')
                self.assertEqual(r.status_code, 200, m['key'])
