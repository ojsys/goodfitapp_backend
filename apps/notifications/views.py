"""
GET   /api/notifications/                 {sections: [{title, items}], unread}
GET   /api/notifications/unread/          {unread}
POST  /api/notifications/read-all/
POST  /api/notifications/<id>/read/
GET/PATCH /api/notifications/settings/    {ride_reminders, props_comments, club_announcements, messages}
POST  /api/notifications/devices/         {token, platform}   register for push
DELETE /api/notifications/devices/        {token}             on log out
"""

from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.age_gate import safe_zone

from . import push
from .models import TOGGLEABLE, Device, Notification, NotificationSettings
from .services import unread_count

ICONS = {'props': 'props', 'comment': 'person', 'follow': 'person', 'wave': 'person', 'ride_invite': 'person',
         'ride_update': 'ride', 'ride_reminder': 'ride', 'announcement': 'announce', 'report_update': 'flag',
         'warning': 'flag', 'segment': 'trophy', 'challenge': 'bolt', 'match': 'heart'}
PERSON_KINDS = {'comment', 'follow', 'wave', 'ride_invite'}


def _when(dt, user):
    tz = safe_zone(user.timezone)
    now = timezone.now()
    s = (now - dt).total_seconds()
    if s < 60:
        return 'now'
    if s < 3600:
        return f'{int(s // 60)}m'
    if s < 86400:
        return f'{int(s // 3600)}h'
    local = dt.astimezone(tz)
    if (now.astimezone(tz).date() - local.date()).days < 7:
        return local.strftime('%a')
    return f'{local:%b} {local.day}'


def item(n, viewer, request=None):
    from apps.social.feed import person
    show_person = n.kind in PERSON_KINDS and n.actor_id
    return {
        'id': n.id,
        'kind': n.kind,
        'parts': n.parts,
        'icon': ICONS.get(n.kind, 'bell'),
        'person': person(n.actor, request) if show_person else None,
        'link': n.link,
        'unread': n.read_at is None,
        'when': _when(n.updated_at, viewer),
    }


class NotificationsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        qs = list(Notification.objects.filter(recipient=user).select_related('actor')[:100])
        week_ago = timezone.now() - timedelta(days=7)
        new = [n for n in qs if n.read_at is None]
        week = [n for n in qs if n.read_at is not None and n.updated_at >= week_ago]
        older = [n for n in qs if n.read_at is not None and n.updated_at < week_ago]
        sections = [(t, rows) for t, rows in [('New', new), ('Earlier This Week', week), ('Earlier', older)] if rows]
        return Response({'sections': [{'title': t, 'items': [item(n, user, request) for n in rows]}
                                      for t, rows in sections],
                         'unread': len(new)})


class UnreadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({'unread': unread_count(request.user)})


class ReadAllView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        n = Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=timezone.now())
        return Response({'marked': n, 'unread': 0})


class ReadOneView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        n = get_object_or_404(Notification, pk=pk, recipient=request.user)
        if n.read_at is None:
            n.read_at = timezone.now()
            n.save(update_fields=['read_at'])
        return Response({'unread': unread_count(request.user)})


def settings_payload(user):
    s = NotificationSettings.of(user)
    return {k: getattr(s, k) for k in TOGGLEABLE} | {'push_available': push.enabled()}


class SettingsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(settings_payload(request.user))

    def patch(self, request):
        s = NotificationSettings.of(request.user)
        for k in TOGGLEABLE:
            if k in request.data:
                setattr(s, k, bool(request.data[k]))
        s.save()
        return Response(settings_payload(request.user))


class DevicesView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    allow_pending_member = True

    def post(self, request):
        token = (request.data.get('token') or '').strip()
        platform = request.data.get('platform')
        if not token or platform not in dict(Device.PLATFORMS):
            return Response({'code': 'invalid', 'message': 'token and platform (ios|android) are required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        Device.objects.update_or_create(token=token[:300], defaults={'user': request.user, 'platform': platform})
        return Response({'registered': True, 'push_available': push.enabled()})

    def delete(self, request):
        Device.objects.filter(user=request.user, token=(request.data.get('token') or '')[:300]).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
