"""
You, Edit profile and Settings (Phase 6).

GET/PATCH /api/auth/me/          edit profile: name, neighborhood, headline, bio, interests, intents, units
GET/PATCH /api/auth/settings/    everything on the Settings screen
POST      /api/auth/email/       {email, password}  change sign-in email
GET       /api/auth/export/      download my data (JSON)
POST      /api/auth/delete/      {password} or {confirm: "DELETE"} for Apple/Google accounts
"""

import json

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .serializers import MeSerializer

BIO_MAX = 150
VISIBILITY = ('everyone', 'followers', 'club', 'me')


def _bad(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({'code': code, 'message': message}, status=http)


def _me(user, request):
    return MeSerializer(user, context={'request': request}).data


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(_me(request.user, request))

    def patch(self, request):
        u, d = request.user, request.data
        fields = []
        if 'name' in d:
            name = ' '.join((d.get('name') or '').split())
            if len(name) < 1:
                return _bad('name', 'Add your name.')
            first, _, last = name.partition(' ')
            u.first_name, u.last_name, u.display_name = first[:50], last[:50], name[:100]
            fields += ['first_name', 'last_name', 'display_name']
        for key, limit in (('neighborhood', 80), ('headline', 80)):
            if key in d:
                setattr(u, key, ' '.join((d.get(key) or '').split())[:limit])
                fields.append(key)
        if 'bio' in d:
            bio = (d.get('bio') or '').strip()
            if len(bio) > BIO_MAX:
                return _bad('bio', f'Keep your bio under {BIO_MAX} characters.')
            u.bio = bio
            fields.append('bio')
        if 'interests' in d:
            picks = list(dict.fromkeys(d.get('interests') or []))
            if any(p not in User.INTERESTS for p in picks):
                return _bad('interests', 'Pick from the list.')
            if not 1 <= len(picks) <= User.MAX_INTERESTS:
                return _bad('interests', f'Pick 1 to {User.MAX_INTERESTS}.')
            u.interests = picks
            fields.append('interests')
        if 'intents' in d:
            picks = list(dict.fromkeys(d.get('intents') or []))
            if not picks or any(p not in User.INTENTS for p in picks):
                return _bad('intents', 'Pick at least one.')
            u.intents = picks
            fields.append('intents')
        if 'units' in d:
            if d['units'] not in ('mi', 'km'):
                return _bad('units', 'Miles or kilometers.')
            u.units = d['units']
            fields.append('units')
        if fields:
            u.save(update_fields=fields)
        return Response(_me(u, request))


def settings_payload(user):
    from apps.notifications.views import settings_payload as notif
    from apps.safety.models import Block, Report
    reports = Report.objects.filter(reporter=user)
    return {
        'plan': user.plan,
        'email': user.email,
        'name': user.full_name,
        'neighborhood': user.neighborhood,
        'has_password': user.has_usable_password(),
        'signin_provider': 'apple' if user.apple_sub else ('google' if user.google_sub else None),
        'privacy_zones_on': user.privacy_zones_on,
        'privacy_zones': user.privacy_zones.count(),
        'hide_track_ends': user.hide_track_ends,
        'default_visibility': user.default_visibility,
        'blocked': Block.objects.filter(blocker=user).count(),
        'reports': {'open': reports.filter(status='open').count(),
                    'resolved': reports.filter(status='resolved').count()},
        'match': {'visible': user.match_opted_in, 'paused': user.match_paused},
        'notifications': notif(user),
    }


class SettingsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(settings_payload(request.user))

    def patch(self, request):
        u, d = request.user, request.data
        fields = []
        for key in ('privacy_zones_on', 'hide_track_ends', 'match_paused'):
            if key in d:
                setattr(u, key, bool(d[key]))
                fields.append(key)
        if 'default_visibility' in d:
            if d['default_visibility'] not in VISIBILITY:
                return _bad('visibility', 'Pick who sees your activities.')
            u.default_visibility = d['default_visibility']
            fields.append('default_visibility')
        if 'match_visible' in d:
            # "Show me in A Good Match" is the romantic intent.
            intents = [i for i in (u.intents or []) if i != 'romantic']
            if d['match_visible']:
                intents.append('romantic')
            u.intents = intents or ['community']
            fields.append('intents')
        if fields:
            u.save(update_fields=fields)
        if 'notifications' in d and isinstance(d['notifications'], dict):
            from apps.notifications.models import TOGGLEABLE, NotificationSettings
            s = NotificationSettings.of(u)
            for k in TOGGLEABLE:
                if k in d['notifications']:
                    setattr(s, k, bool(d['notifications'][k]))
            s.save()
        return Response(settings_payload(u))


class EmailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        u = request.user
        email = (request.data.get('email') or '').strip().lower()
        try:
            validate_email(email)
        except ValidationError:
            return _bad('email', 'That doesn’t look like an email address.')
        if u.has_usable_password() and not u.check_password(request.data.get('password') or ''):
            return _bad('password', 'That password isn’t right.', status.HTTP_403_FORBIDDEN)
        if User.objects.filter(email__iexact=email).exclude(pk=u.pk).exists():
            return _bad('taken', 'Another account uses that email.')
        u.email = email
        u.save(update_fields=['email'])
        return Response(_me(u, request))


class PasswordView(APIView):
    """Set or change the password (Apple/Google accounts can add one)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        u = request.user
        new = request.data.get('new_password') or ''
        if u.has_usable_password() and not u.check_password(request.data.get('old_password') or ''):
            return _bad('password', 'Your current password isn’t right.', status.HTTP_403_FORBIDDEN)
        try:
            password_validation.validate_password(new, u)
        except ValidationError as e:
            return _bad('weak', ' '.join(e.messages))
        u.set_password(new)
        u.save(update_fields=['password'])
        return Response({'ok': True})


def export(user):
    """Everything a member put into A Good Fit, as plain data."""
    from apps.activities.models import Activity
    from apps.chats.models import ChatMessage
    from apps.routes.models import Route
    from apps.safety.models import Block, Report
    from apps.social.models import ClubMembership, Comment, Follow, Post, PrivacyZone

    def rows(qs, *fields):
        return [{f: (v.isoformat() if hasattr(v, 'isoformat') else v) for f, v in zip(fields, r)}
                for r in qs.values_list(*fields)]

    return {
        'exported_at': timezone.now().isoformat(),
        'profile': {k: v for k, v in MeSerializer(user).data.items() if k not in ('goals', 'stats', 'preferences')},
        'activities': rows(Activity.objects.filter(user=user), 'id', 'type', 'title', 'start_time', 'distance',
                           'moving_time', 'elevation_gain', 'visibility', 'route'),
        'posts': rows(Post.objects.filter(author=user), 'id', 'type', 'text', 'audience', 'created_at'),
        'comments': rows(Comment.objects.filter(author=user), 'id', 'text', 'post_id', 'activity_id', 'created_at'),
        'routes': rows(Route.objects.filter(owner=user), 'id', 'name', 'distance_m', 'line', 'created_at'),
        'following': list(Follow.objects.filter(follower=user).values_list('followee_id', flat=True)),
        'followers': list(Follow.objects.filter(followee=user).values_list('follower_id', flat=True)),
        'clubs': rows(ClubMembership.objects.filter(user=user), 'club__name', 'role', 'joined_at'),
        'privacy_zones': rows(PrivacyZone.objects.filter(user=user), 'label', 'latitude', 'longitude', 'radius_m'),
        'messages_sent': rows(ChatMessage.objects.filter(sender=user), 'chat_id', 'body', 'attachment',
                              'created_at'),
        'blocked': list(Block.objects.filter(blocker=user).values_list('blocked_id', flat=True)),
        'reports_made': rows(Report.objects.filter(reporter=user), 'target_kind', 'reason', 'status',
                             'created_at'),
    }


class ExportView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'export'

    def get_throttles(self):
        from rest_framework.throttling import ScopedRateThrottle
        return [ScopedRateThrottle()]

    def get(self, request):
        body = json.dumps(export(request.user), indent=2, default=str)
        r = HttpResponse(body, content_type='application/json')
        r['Content-Disposition'] = f'attachment; filename="agoodfit-data-{timezone.now():%Y-%m-%d}.json"'
        return r


class DeleteAccountView(APIView):
    """Delete the account and everything in it. Messages in group chats stay
    as "Someone" so threads still make sense."""

    permission_classes = [permissions.IsAuthenticated]
    allow_pending_member = True

    def post(self, request):
        u = request.user
        if u.has_usable_password():
            if not u.check_password(request.data.get('password') or ''):
                return _bad('password', 'That password isn’t right.', status.HTTP_403_FORBIDDEN)
        elif request.data.get('confirm') != 'DELETE':
            return _bad('confirm', 'Type DELETE to confirm.')
        with transaction.atomic():
            from apps.notifications.models import Device
            Device.objects.filter(user=u).delete()
            u.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
