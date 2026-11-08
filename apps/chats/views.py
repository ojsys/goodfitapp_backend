"""
Chats API (Phase 4).

GET  /api/chats/                       inbox: ride chats, direct, (match: Phase 8)
GET  /api/chats/unread/                total unread (Home header)
POST /api/chats/direct/ {user}         open (or start) a DM
GET  /api/chats/<id>/                  header
GET  /api/chats/<id>/messages/?after=&before=   newest 50, or newer than `after`
POST /api/chats/<id>/messages/         send (JSON, or multipart with `photo`)
POST /api/chats/<id>/read/ {last_id}
DELETE /api/chats/messages/<id>/       sender, or a club team member who can moderate
PATCH  /api/chats/messages/<id>/location/   live location update by the sender

Delivery is by polling `?after=` (works on any WSGI host). A websocket
transport can be added on an ASGI host without changing these rules.
"""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.routes.views import visible_routes
from apps.users.models import User

from . import services as svc
from .models import Chat, ChatMember, ChatMessage

PAGE = 50


def _bad(code, message, http=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({'code': code, 'message': message, **extra}, status=http)


def _chat_for(user, pk):
    chat = get_object_or_404(Chat.objects.select_related('event', 'event__club'), pk=pk)
    if not ChatMember.objects.filter(chat=chat, user=user).exists():
        return None
    return chat


class InboxView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        rows = [svc.inbox_row(c, request.user, request) for c in svc.chats_for(request.user)]
        rows.sort(key=lambda r: (r['closed'], r['at']), reverse=False)
        ride = sorted([r for r in rows if r['kind'] == 'ride'], key=lambda r: (r['closed'], -_ts(r['at'])))
        direct = sorted([r for r in rows if r['kind'] == 'direct'], key=lambda r: -_ts(r['at']))
        return Response({'ride': ride, 'direct': direct, 'match': [],
                         'unread': sum(r['unread'] for r in rows)})


def _ts(iso):
    from datetime import datetime
    return datetime.fromisoformat(iso).timestamp()


class UnreadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({'unread': svc.total_unread(request.user)})


class DirectView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        other = User.objects.filter(pk=request.data.get('user'), is_active=True).first()
        if not other or other.id == request.user.id:
            return _bad('invalid', 'Pick someone to message.')
        if not svc.direct_allowed(request.user, other):
            return _bad('blocked', 'You can’t message this person.', status.HTTP_403_FORBIDDEN)
        chat = svc.direct_chat(request.user, other)
        return Response(svc.chat_header(chat, request.user, request))


class ChatView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        chat = _chat_for(request.user, pk)
        if chat is None:
            return _bad('not_found', 'This chat isn’t available.', status.HTTP_404_NOT_FOUND)
        return Response(svc.chat_header(chat, request.user, request))


class MessagesView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    throttle_scope = 'messages'

    def get_throttles(self):
        # Rate-limit sending only (requirements: rate-limit messaging).
        return [ScopedRateThrottle()] if self.request.method == 'POST' else []

    def get(self, request, pk):
        chat = _chat_for(request.user, pk)
        if chat is None:
            return _bad('not_found', 'This chat isn’t available.', status.HTTP_404_NOT_FOUND)
        qs = svc.visible_messages(chat, request.user)
        after = request.query_params.get('after')
        before = request.query_params.get('before')
        if after:
            items = list(qs.filter(id__gt=int(after)).order_by('id')[:200])
        else:
            if before:
                qs = qs.filter(id__lt=int(before))
            items = list(qs.order_by('-id')[:PAGE])[::-1]
        badges = svc.role_badges(chat)
        m = svc.member(chat, request.user)
        return Response({
            'items': [svc.message_item(x, request.user, badges, request) for x in items],
            'has_more': bool(not after and len(items) == PAGE),
            'closed': chat.is_closed,
            'locked_until': (m.locked_until.isoformat() if m and m.locked_until and m.locked_until > timezone.now()
                             else None),
        })

    def post(self, request, pk):
        chat = _chat_for(request.user, pk)
        if chat is None:
            return _bad('not_found', 'This chat isn’t available.', status.HTTP_404_NOT_FOUND)
        d = request.data
        body = (d.get('body') or '').strip()
        if len(body) > ChatMessage.MAX_BODY:
            return _bad('too_long', 'That message is too long.')
        att = d.get('attachment') or ''
        route = photo = lat = lng = live = None
        if att == 'route':
            route = visible_routes(request.user).filter(pk=d.get('route')).first()
            if not route:
                return _bad('route', 'That route isn’t available.')
        elif att == 'photo':
            photo = request.FILES.get('photo')
            if not photo:
                return _bad('photo', 'Attach a photo.')
        elif att == 'location':
            try:
                lat, lng = float(d['latitude']), float(d['longitude'])
            except (KeyError, TypeError, ValueError):
                return _bad('location', 'Location is missing.')
            if d.get('live_minutes'):
                live = int(d['live_minutes'])
                if live not in (15, 30, 60):
                    return _bad('location', 'Share for 15, 30 or 60 minutes.')
        elif att:
            return _bad('attachment', 'Unknown attachment.')
        if not body and not att:
            return _bad('empty', 'Write a message first.')
        if chat.kind == 'direct':
            other = svc.other_in_direct(chat, request.user)
            if not other or not svc.direct_allowed(request.user, other):
                return _bad('blocked', 'You can’t message this person.', status.HTTP_403_FORBIDDEN)
        try:
            msg = svc.send(chat, request.user, body=body, attachment=att, route=route, photo=photo, lat=lat, lng=lng,
                           live_minutes=live, client_id=(d.get('client_id') or '')[:40])
        except svc.ChatClosed:
            return _bad('closed', 'This chat is read-only now.', status.HTTP_409_CONFLICT)
        except svc.SlowMode as e:
            return _bad('slow_mode', 'You’re sending a lot quickly.', status.HTTP_429_TOO_MANY_REQUESTS,
                        locked_until=e.until.isoformat(), paused=e.paused)
        return Response(svc.message_item(msg, request.user, svc.role_badges(chat), request),
                        status=status.HTTP_201_CREATED)


class ReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            last = int(request.data.get('last_id') or 0)
        except (TypeError, ValueError):
            return _bad('invalid', 'last_id must be a number.')
        m = ChatMember.objects.filter(chat_id=pk, user=request.user).first()
        if not m:
            return _bad('not_found', 'This chat isn’t available.', status.HTTP_404_NOT_FOUND)
        if last > m.last_read_id:
            m.last_read_id = last
            m.save(update_fields=['last_read_id'])
        return Response({'last_read_id': m.last_read_id})


class MessageView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        msg = get_object_or_404(ChatMessage.objects.select_related('chat', 'chat__event'), pk=pk)
        if msg.sender_id != request.user.id and not svc.can_moderate(msg.chat, request.user):
            return _bad('forbidden', 'You can’t remove this message.', status.HTTP_403_FORBIDDEN)
        msg.removed_by, msg.removed_at = request.user, timezone.now()
        msg.save(update_fields=['removed_by', 'removed_at'])
        if msg.sender_id != request.user.id and msg.chat.event and msg.chat.event.club_id:
            from apps.social.models import ClubTeamLog
            ClubTeamLog.objects.create(club_id=msg.chat.event.club_id, actor=request.user,
                                       action=f'Removed a message in “{msg.chat.event.title}”')
        return Response(status=status.HTTP_204_NO_CONTENT)


class LiveLocationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        msg = get_object_or_404(ChatMessage, pk=pk, sender=request.user, attachment='location')
        if not msg.live_until or timezone.now() >= msg.live_until:
            return _bad('ended', 'This live location has ended.', status.HTTP_409_CONFLICT)
        if request.data.get('stop'):
            msg.live_until = timezone.now()
        else:
            try:
                msg.latitude, msg.longitude = float(request.data['latitude']), float(request.data['longitude'])
            except (KeyError, TypeError, ValueError):
                return _bad('location', 'Location is missing.')
        msg.save(update_fields=['latitude', 'longitude', 'live_until', 'updated_at'])
        return Response({'ok': True})
