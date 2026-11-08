"""Phase 5: reports on every target, Your reports, hide with Undo, two-way
blocks everywhere, and the moderation outcomes."""

from django.test import override_settings

from apps.social.models import Club, ClubMembership, Comment, Follow, Post, Wave
from apps.social.tests import Base

from . import moderation
from .models import Block, ModerationAction, Report

NO_THROTTLE = {'DEFAULT_THROTTLE_RATES': {'auth': '1000/hour', 'password_reset': '1000/hour',
                                          'messages': '10000/hour', 'reports': '1000/hour'}}


def feed_ids(test, user, tab='following'):
    r = test.client_for(user).get(f'/api/social/feed/?tab={tab}')
    test.assertEqual(r.status_code, 200, r.data)
    return [(i['kind'], i['id']) for i in r.data['items']]


@override_settings(REST_FRAMEWORK={**__import__('django.conf').conf.settings.REST_FRAMEWORK, **NO_THROTTLE})
class ReportTests(Base):
    def report(self, user, **body):
        return self.client_for(user).post('/api/safety/reports/', body, format='json')

    def test_reasons_are_per_target_and_other_needs_details(self):
        post = Post.objects.create(author=self.friend, text='hi', audience='followers')
        r = self.report(self.me, target_kind='post', target_id=post.id, reason='under21')
        self.assertEqual(r.data['code'], 'reason')  # under21 is for people
        r = self.report(self.me, target_kind='post', target_id=post.id, reason='other')
        self.assertEqual(r.data['code'], 'details')
        r = self.report(self.me, target_kind='member', target_id=self.me.id, reason='fake')
        self.assertEqual(r.data['code'], 'self')

    def test_post_report_hides_it_and_dedupes(self):
        post = Post.objects.create(author=self.friend, text='buy my stuff', audience='followers')
        self.assertIn(('post', post.id), feed_ids(self, self.me))
        r = self.report(self.me, target_kind='post', target_id=post.id, reason='spam')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertNotIn(('post', post.id), feed_ids(self, self.me))
        # Still there for everyone else.
        self.assertIn(('post', post.id), feed_ids(self, self.friend))
        again = self.report(self.me, target_kind='post', target_id=post.id, reason='unsafe', details='more')
        self.assertEqual(again.status_code, 200)
        rep = Report.objects.get()
        self.assertEqual((rep.reason, rep.priority, rep.snapshot), ('unsafe', Report.PRIORITY_UNSAFE, 'buy my stuff'))

    def test_cant_report_what_you_cant_see(self):
        private = Post.objects.create(author=self.stranger, text='x', audience='followers')
        r = self.report(self.me, target_kind='post', target_id=private.id, reason='spam')
        self.assertEqual(r.status_code, 404)

    def test_comment_and_activity_reports(self):
        act = self.act(self.friend)
        c = Comment.objects.create(author=self.stranger, activity=act, text='nasty')
        r = self.report(self.me, target_kind='comment', target_id=c.id, reason='harassment')
        self.assertEqual(r.status_code, 201, r.data)
        rep = Report.objects.get(target_kind='comment')
        self.assertEqual((rep.target_user, rep.context), (self.stranger, 'Comment on Marvel’s activity'))
        r = self.report(self.me, target_kind='activity', target_id=act.id, reason='inappropriate')
        self.assertEqual(r.status_code, 201)
        self.assertNotIn(('activity', act.id), feed_ids(self, self.me))

    def test_your_reports_open_and_resolved(self):
        r = self.report(self.me, target_kind='member', target_id=self.stranger.id, reason='under21',
                        context='Fit Buddies profile')
        self.assertEqual(r.status_code, 201)
        mine = self.client_for(self.me).get('/api/safety/reports/').data
        item = mine['open'][0]
        self.assertEqual((item['title'], item['badge']), ('Alex', 'Under review'))
        self.assertEqual(item['meta'], 'Fit Buddies profile · Seems under 21 · Today')
        self.assertIn('Alex is hidden from your suggestions while we look.', item['body'])
        # Hidden from suggestions while it's reviewed.
        buddies = self.client_for(self.me).get('/api/social/buddies/').data['items']
        self.assertNotIn(self.stranger.id, [b['person']['id'] for b in buddies])
        # Someone else can't see my reports.
        self.assertEqual(self.client_for(self.friend).get('/api/safety/reports/').data['open'], [])

        moderation.decide(Report.objects.get(), 'age_check', self.friend)
        mine = self.client_for(self.me).get('/api/safety/reports/').data
        self.assertEqual(mine['open'], [])
        self.assertEqual(mine['resolved'][0]['badge'], 'Action taken')
        self.stranger.refresh_from_db()
        self.assertFalse(self.stranger.is_active)
        self.assertTrue(ModerationAction.objects.filter(member=self.stranger, kind='age_check').exists())


@override_settings(REST_FRAMEWORK={**__import__('django.conf').conf.settings.REST_FRAMEWORK, **NO_THROTTLE})
class ModerationTests(Base):
    def test_remove_and_warn_resolves_every_report_on_it(self):
        post = Post.objects.create(author=self.friend, text='spam spam', audience='followers')
        Follow.objects.create(follower=self.stranger, followee=self.friend)
        for u in (self.me, self.stranger):
            self.client_for(u).post('/api/safety/reports/', {'target_kind': 'post', 'target_id': post.id,
                                                              'reason': 'spam'}, format='json')
        n = moderation.decide(Report.objects.first(), 'remove_warn', self.me)
        self.assertEqual(n, 2)
        self.assertFalse(Post.objects.filter(pk=post.id).exists())
        self.assertEqual(set(Report.objects.values_list('outcome', flat=True)), {'action_taken'})
        self.assertIn('We removed the post', Report.objects.first().outcome_note)
        self.assertEqual(set(ModerationAction.objects.values_list('kind', flat=True)), {'removed_content', 'warned'})

    def test_no_violation(self):
        r = Report.objects.create(reporter=self.me, target_kind='member', target_user=self.friend,
                                  target_id=self.friend.id, reason='fake')
        moderation.decide(r, 'no_violation', self.stranger)
        r.refresh_from_db()
        self.assertEqual((r.status, r.outcome), ('resolved', 'no_violation'))
        self.friend.refresh_from_db()
        self.assertTrue(self.friend.is_active)

    def test_banned_members_leave_the_feed_and_cant_sign_in(self):
        act = self.act(self.friend)
        self.assertIn(('activity', act.id), feed_ids(self, self.me))
        r = Report.objects.create(reporter=self.me, target_kind='member', target_user=self.friend,
                                  target_id=self.friend.id, reason='harassment')
        moderation.decide(r, 'ban', self.stranger)
        self.assertNotIn(('activity', act.id), feed_ids(self, self.me))
        self.assertEqual(self.client_for(self.friend).get('/api/social/feed/').status_code, 401)

    def test_queue_order(self):
        a = Report.objects.create(reporter=self.me, target_kind='member', target_id=1, reason='fake')
        b = Report.objects.create(reporter=self.me, target_kind='member', target_id=2, reason='under21', priority=1)
        c = Report.objects.create(reporter=self.me, target_kind='member', target_id=3, reason='unsafe', priority=0)
        d = Report.objects.create(reporter=self.me, target_kind='member', target_id=4, reason='unsafe', priority=0,
                                  status='resolved')
        # Through the real admin page, as a moderator sees it.
        self.me.is_staff = self.me.is_superuser = True
        self.me.save()
        self.client.force_login(self.me)
        page = self.client.get('/admin/safety/report/?queue=all')
        self.assertEqual(page.status_code, 200)
        self.assertEqual([r.id for r in page.context['cl'].result_list], [c.id, b.id, a.id, d.id])
        page = self.client.get('/admin/safety/report/')
        self.assertEqual([r.id for r in page.context['cl'].result_list], [c.id, b.id, a.id])
        self.assertContains(page, 'Moderation queue · 3 open · 1 unsafe · 1 under 21')


class BlockEverywhereTests(Base):
    def setUp(self):
        super().setUp()
        self.club = Club.objects.create(name='GoodCo Bike Club', initials='GC')
        for u in (self.me, self.friend, self.stranger):
            ClubMembership.objects.create(club=self.club, user=u)

    def test_blocked_disappears_everywhere(self):
        act = self.act(self.friend, vis='everyone', distance=40000)
        post = Post.objects.create(author=self.friend, text='hello', audience='followers')
        Comment.objects.create(author=self.friend, activity=self.act(self.stranger, vis='everyone'), text='nice')
        c = self.client_for(self.me)
        self.assertEqual(c.post(f'/api/safety/blocks/{self.friend.id}/').status_code, 200)
        self.assertFalse(Follow.objects.filter(follower=self.me, followee=self.friend).exists())

        self.assertNotIn(('activity', act.id), feed_ids(self, self.me, 'club'))
        self.assertNotIn(('post', post.id), feed_ids(self, self.me))
        # Two-way: they don't see me either.
        mine = self.act(self.me, vis='everyone')
        self.assertNotIn(('activity', mine.id), feed_ids(self, self.friend, 'club'))
        # Detail, props, comments.
        self.assertEqual(c.get(f'/api/activities/{act.id}/detail/').status_code, 404)
        self.assertEqual(c.post(f'/api/social/activities/{act.id}/props/').status_code, 404)
        # Follow and wave refused both ways.
        self.assertEqual(c.post(f'/api/social/people/{self.friend.id}/follow/').status_code, 404)
        self.assertEqual(self.client_for(self.friend).post(f'/api/social/people/{self.me.id}/wave/').status_code, 404)
        self.assertFalse(Wave.objects.exists())
        # Leaderboard, members, search.
        board = c.get(f'/api/social/clubs/{self.club.id}/leaderboard/').data['items']
        self.assertNotIn(self.friend.id, [r['person']['id'] for r in board])
        members = c.get(f'/api/social/clubs/{self.club.id}/members/').data['items']
        self.assertNotIn(self.friend.id, [m['person']['id'] for m in members])
        crew = c.get('/api/social/crew/?q=Marv').data
        self.assertEqual(crew, [])
        buddies = c.get('/api/social/buddies/').data['items']
        self.assertNotIn(self.friend.id, [b['person']['id'] for b in buddies])

    def test_comments_hidden_and_unblock_restores(self):
        act = self.act(self.stranger, vis='everyone')
        Comment.objects.create(author=self.friend, activity=act, text='nice')
        c = self.client_for(self.me)
        c.post(f'/api/safety/blocks/{self.friend.id}/')
        self.assertEqual(c.get(f'/api/social/activities/{act.id}/comments/').data['items'], [])
        self.assertEqual([p['id'] for p in c.get('/api/safety/blocks/').data['items']], [self.friend.id])
        c.delete(f'/api/safety/blocks/{self.friend.id}/')
        self.assertEqual(len(c.get(f'/api/social/activities/{act.id}/comments/').data['items']), 1)
        self.assertFalse(Block.objects.exists())

    def test_hide_and_undo(self):
        act = self.act(self.friend)
        c = self.client_for(self.me)
        self.assertEqual(c.post(f'/api/safety/hide/activity/{act.id}/').status_code, 200)
        self.assertNotIn(('activity', act.id), feed_ids(self, self.me))
        c.delete(f'/api/safety/hide/activity/{act.id}/')
        self.assertIn(('activity', act.id), feed_ids(self, self.me))
        self.assertEqual(c.post('/api/safety/hide/nope/1/').status_code, 400)
        self.assertEqual(c.post('/api/safety/hide/post/999999/').status_code, 404)
