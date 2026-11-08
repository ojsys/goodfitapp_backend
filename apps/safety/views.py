"""
Safety endpoints.

POST   /api/safety/reports/               {target_kind, target_id, reason, details, block, context}
GET    /api/safety/reports/               Your reports: {open: [...], resolved: [...]}
GET    /api/safety/blocks/                Blocked people
POST/DELETE /api/safety/blocks/<user_id>/
POST/DELETE /api/safety/hide/<kind>/<id>/ kind: post | activity | person (not interested)
"""

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.age_gate import safe_zone
from apps.users.models import User

from . import visibility
from .models import REASONS, Block, Report


def _bad(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({'code': code, 'message': message}, status=http)


def _name(u):
    return (u.first_name or (u.display_name or '').split(' ')[0] or 'Someone') if u else 'Someone'


def block(blocker, blocked):
    """Two-way: unfollow both ways, drop waves and invites, hide from chats."""
    from apps.social.models import Follow, RideInvite, Wave
    Block.objects.get_or_create(blocker=blocker, blocked=blocked)
    Follow.objects.filter(Q(follower=blocker, followee=blocked) | Q(follower=blocked, followee=blocker)).delete()
    Wave.objects.filter(Q(sender=blocker, recipient=blocked) | Q(sender=blocked, recipient=blocker)).delete()
    RideInvite.objects.filter(Q(sender=blocker, recipient=blocked) | Q(sender=blocked, recipient=blocker)).delete()
    visibility.forget(blocker)


def hide(member, kind, obj_id):
    from apps.social.models import Hide
    field, hkind = {'post': ('target_post_id', 'hidden_post'), 'activity': ('target_activity_id', 'hidden_activity'),
                    'person': ('target_user_id', 'not_interested')}[kind]
    Hide.objects.get_or_create(member=member, kind=hkind, **{field: obj_id})


def unhide(member, kind, obj_id):
    from apps.social.models import Hide
    field, hkind = {'post': ('target_post_id', 'hidden_post'), 'activity': ('target_activity_id', 'hidden_activity'),
                    'person': ('target_user_id', 'not_interested')}[kind]
    Hide.objects.filter(member=member, kind=hkind, **{field: obj_id}).delete()


# ----------------------------------------------------------------- targets

def _resolve_target(kind, target_id, reporter, context):
    """(target_user, context label, snapshot) for a report, or raise 404.
    Only things the reporter can actually see can be reported."""
    from django.http import Http404
    if kind == 'member':
        u = get_object_or_404(User, pk=target_id)
        snap = '\n'.join(x for x in [
            f'Name: {u.display_name or u.full_name}',
            f'Bio: {getattr(u, "bio", "") or ""}'.strip(),
            f'Prompt: {u.prompt_question} / {u.prompt_answer}' if getattr(u, 'prompt_answer', '') else '',
            f'Photo: {u.avatar.url}' if getattr(u, 'avatar', None) else '',
        ] if x and not x.endswith(': '))
        return u, (context or 'Profile'), snap
    if kind == 'message':
        from apps.chats.models import ChatMember, ChatMessage
        from apps.chats.services import chat_title
        msg = get_object_or_404(ChatMessage.objects.select_related('chat', 'sender'), pk=target_id)
        if not ChatMember.objects.filter(chat=msg.chat, user=reporter).exists():
            raise Http404
        # Auto-attach: the reported message plus the five before it.
        before = list(ChatMessage.objects.filter(chat=msg.chat, id__lt=msg.id).select_related('sender')
                      .order_by('-id')[:5])[::-1]
        lines = [f'{"> " if m.id == msg.id else "  "}{_name(m.sender)} ({m.created_at:%Y-%m-%d %H:%M} UTC): '
                 f'{m.body or "[" + (m.attachment or "message") + "]"}' for m in before + [msg]]
        return msg.sender, f'Message in {chat_title(msg.chat, reporter)}'[:120], '\n'.join(lines)
    if kind == 'post':
        from apps.social.models import Post
        from apps.social.privacy import can_view_post
        p = get_object_or_404(Post.objects.select_related('author'), pk=target_id)
        if not can_view_post(reporter, p):
            raise Http404
        snap = p.text + (f'\nPhoto: {p.photo.url}' if p.photo else '')
        return p.author, (context or 'Post on the feed'), snap
    if kind == 'activity':
        from apps.activities.models import Activity
        from apps.social.privacy import can_view_activity
        a = get_object_or_404(Activity.objects.select_related('user'), pk=target_id)
        if not can_view_activity(reporter, a):
            raise Http404
        return a.user, (context or f'Activity · {a.title}')[:120], f'{a.title}\n{getattr(a, "description", "") or ""}'.strip()
    if kind == 'comment':
        from apps.social.models import Comment
        from apps.social.privacy import can_view_activity, can_view_post
        c = get_object_or_404(Comment.objects.select_related('author', 'post__author', 'activity__user'), pk=target_id)
        on = c.post or c.activity
        if (c.post and not can_view_post(reporter, c.post)) or (c.activity and not can_view_activity(reporter, c.activity)):
            raise Http404
        owner = c.post.author if c.post else c.activity.user
        label = f'Comment on {_name(owner)}’s {"post" if c.post else "activity"}' if on else 'Comment'
        return c.author, label, c.text
    raise Http404


# ------------------------------------------------------------ your reports

ICON = {'member': 'person', 'message': 'chat', 'post': 'post', 'comment': 'chat', 'activity': 'activity'}


def _when(dt, user):
    local = timezone.localtime(dt, safe_zone(user.timezone))
    today = timezone.localtime(timezone.now(), safe_zone(user.timezone)).date()
    if local.date() == today:
        return 'Today'
    if (today - local.date()).days == 1:
        return 'Yesterday'
    return f'{local:%b} {local.day}'


def report_item(r, viewer):
    who = _name(r.target_user)
    title = {
        'member': who,
        'message': r.context or 'Message',
        'post': f'{who}’s post',
        'activity': f'{who}’s activity',
        'comment': f'Comment by {who}',
    }.get(r.target_kind, who)
    meta = [r.context] if r.target_kind == 'member' and r.context else []
    meta += [r.reason_label, _when(r.created_at, viewer)]
    if r.status == 'open':
        tail = {
            'member': f' {who} is hidden from your suggestions while we look.',
            'post': ' It’s hidden for you while we look.',
            'activity': ' It’s hidden for you while we look.',
        }.get(r.target_kind, '')
        lead = ('Safety reports go to the front of the line. We’ll update you here soon.' if r.urgent
                else 'Thanks for flagging this. We’ll update you here within 24 hours.')
        body, badge = lead + tail, 'Under review'
    else:
        body = r.outcome_note or (
            'We reviewed it and it didn’t break our guidelines. You can still block anyone, anytime.'
            if r.outcome == 'no_violation' else 'We took action under our guidelines. Thanks for looking out.')
        badge = 'Action taken' if r.outcome == 'action_taken' else 'No violation'
    return {'id': r.id, 'kind': r.target_kind, 'icon': ICON.get(r.target_kind, 'flag'), 'title': title,
            'meta': ' · '.join(x for x in meta if x), 'body': body, 'badge': badge, 'status': r.status,
            'outcome': r.outcome or None, 'created_at': r.created_at.isoformat()}


class ReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'reports'

    def get_throttles(self):
        if self.request.method != 'POST':
            return []
        from rest_framework.throttling import ScopedRateThrottle
        return [ScopedRateThrottle()]

    def get(self, request):
        qs = Report.objects.filter(reporter=request.user).select_related('target_user')
        return Response({
            'open': [report_item(r, request.user) for r in qs.filter(status='open').order_by('-created_at')],
            'resolved': [report_item(r, request.user) for r in qs.filter(status='resolved').order_by('-resolved_at')[:50]],
        })

    def post(self, request):
        d = request.data
        kind = d.get('target_kind')
        reason = d.get('reason')
        details = (d.get('details') or '').strip()[:2000]
        context = (d.get('context') or '').strip()[:80]
        if kind not in REASONS:
            return _bad('target', 'Unknown report target.')
        if reason not in REASONS[kind]:
            return _bad('reason', 'Pick a reason.')
        if reason == 'other' and not details:
            return _bad('details', 'Tell us what happened.')
        try:
            target_id = int(d.get('target_id'))
        except (TypeError, ValueError):
            return _bad('target', 'Missing target.')
        target_user, label, snapshot = _resolve_target(kind, target_id, request.user, context)
        if target_user and target_user.id == request.user.id:
            return _bad('self', 'You can’t report yourself.')

        with transaction.atomic():
            r = Report.objects.filter(reporter=request.user, target_kind=kind, target_id=target_id,
                                      status='open').first()
            created = r is None
            if created:
                r = Report.objects.create(reporter=request.user, target_kind=kind, target_user=target_user,
                                          target_id=target_id, context=label, snapshot=snapshot, reason=reason,
                                          details=details, priority=Report.priority_for(reason))
            else:
                # Same thing reported again: keep one report, take the more urgent reason.
                if Report.priority_for(reason) < r.priority:
                    r.reason, r.priority = reason, Report.priority_for(reason)
                if details:
                    r.details = (r.details + '\n\n' + details).strip()[:4000]
                r.save(update_fields=['reason', 'priority', 'details'])
            # Out of sight while it's reviewed.
            if kind in ('post', 'activity'):
                hide(request.user, kind, target_id)
            elif kind == 'member':
                hide(request.user, 'person', target_id)
            if d.get('block') and target_user:
                block(request.user, target_user)
        return Response({'id': r.id, 'status': r.status, 'urgent': r.urgent, 'blocked': bool(d.get('block'))},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class BlockListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from apps.social.feed import person
        rows = Block.objects.filter(blocker=request.user).select_related('blocked').order_by('-created_at')
        return Response({'items': [dict(person(b.blocked, request), blocked_at=b.created_at.isoformat())
                                   for b in rows]})


class BlockView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        other = get_object_or_404(User, pk=pk)
        if other.id == request.user.id:
            return _bad('self', 'You can’t block yourself.')
        block(request.user, other)
        return Response({'blocked': True})

    def delete(self, request, pk):
        Block.objects.filter(blocker=request.user, blocked_id=pk).delete()
        visibility.forget(request.user)
        return Response({'blocked': False})


class HideView(APIView):
    """Hide a post or activity from your feed, or someone from your
    suggestions. DELETE is the Undo."""

    permission_classes = [permissions.IsAuthenticated]
    KINDS = ('post', 'activity', 'person')

    def _check(self, kind, pk):
        if kind not in self.KINDS:
            return _bad('kind', 'Unknown kind.')
        model = {'post': ('apps.social.models', 'Post'), 'activity': ('apps.activities.models', 'Activity'),
                 'person': ('apps.users.models', 'User')}[kind]
        import importlib
        cls = getattr(importlib.import_module(model[0]), model[1])
        if not cls.objects.filter(pk=pk).exists():
            return _bad('not_found', 'Not found.', status.HTTP_404_NOT_FOUND)
        return None

    def post(self, request, kind, pk):
        err = self._check(kind, pk)
        if err:
            return err
        hide(request.user, kind, pk)
        return Response({'hidden': True})

    def delete(self, request, kind, pk):
        if kind not in self.KINDS:
            return _bad('kind', 'Unknown kind.')
        unhide(request.user, kind, pk)
        return Response({'hidden': False})
