"""
Community endpoints (Phase 3).

GET  /api/social/community/                 hub
GET  /api/social/clubs/<id>/                club page
GET  /api/social/clubs/<id>/members/?offset=
GET  /api/social/clubs/<id>/leaderboard/
GET  /api/social/events/?date=YYYY-MM-DD&type=ride
POST /api/social/events/host/               community ride (Plus) or suggestion
GET  /api/social/buddies/?filter=ride|run|yoga|mornings|near
POST/DELETE /api/social/buddies/<id>/hide/  not interested (+ undo)
POST /api/social/buddies/<id>/invite/       invite to a ride you're going to
PATCH /api/social/me/location/              approximate location for distances
"""

from datetime import date as date_cls, datetime, time

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.events.models import Event, EventRSVP
from apps.routes.models import Route
from apps.routes.views import visible_routes
from apps.users.age_gate import safe_zone
from apps.users.models import User

from . import community
from .feed import person
from .models import Club, ClubMembership, ClubTeamLog, Hide, RideInvite, RideSuggestion


def _bad(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({'code': code, 'message': message}, status=http)


class HubView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(community.hub(request.user, request))


class ClubView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        return Response(community.club_page(club, request.user, request))


class ClubMembersView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        offset = max(0, int(request.query_params.get('offset') or 0))
        return Response({'count': club.memberships.count(),
                         'items': community.club_members(club, request.user, request, offset)})


class ClubLeaderboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        return Response({'items': community.leaders(club, request.user, request)})


class EventsBrowseView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        d = request.query_params.get('date')
        try:
            day = date_cls.fromisoformat(d) if d else None
        except ValueError:
            return _bad('invalid_date', 'Use YYYY-MM-DD.')
        kind = request.query_params.get('type') or None
        return Response(community.browse(request.user, day, kind, request))


class HostEventView(APIView):
    """Host an event: a community ride (Plus, host agreement once) or a
    suggestion to one of your clubs (free)."""

    permission_classes = [permissions.IsAuthenticated]
    ACTIVITIES = ('ride', 'run', 'walk', 'yoga')

    def post(self, request):
        user = request.user
        d = request.data
        mode = d.get('mode')
        if mode not in ('community', 'suggest'):
            return _bad('invalid_mode', 'Pick community ride or suggest to a club.')
        title = (d.get('title') or '').strip()
        if len(title) < 2:
            return _bad('title', 'Name your event to publish.')
        act = d.get('activity_type', 'ride')
        if act not in self.ACTIVITIES:
            return _bad('activity', 'Pick an activity.')
        tz = safe_zone(user.timezone)
        try:
            day = date_cls.fromisoformat(d['date'])
            hh, mm = (int(x) for x in str(d['time']).split(':'))
            start = datetime.combine(day, time(hh, mm), tzinfo=tz)
        except (KeyError, ValueError, TypeError):
            return _bad('when', 'Pick a day and start time.')
        if start <= timezone.now():
            return _bad('when', 'Pick a time in the future.')
        spot = (d.get('meeting_spot') or '').strip()
        if not spot:
            return _bad('spot', 'Add a meeting spot.')
        pace = d.get('pace', 'social')
        if pace not in community.PACE_LABELS:
            return _bad('pace', 'Pick a pace.')
        try:
            cap = int(d.get('capacity') or 20)
        except (TypeError, ValueError):
            return _bad('capacity', 'Spots must be a number.')
        if not 2 <= cap <= 60:
            return _bad('capacity', 'Spots must be between 2 and 60.')
        who = d.get('who_can_join', 'anyone')
        if who not in ('club', 'anyone', 'invite'):
            return _bad('who', 'Pick who can join.')
        route = None
        if d.get('route'):
            route = visible_routes(user).filter(pk=d['route']).first()
            if not route:
                return _bad('route', 'That route isn’t available.')
        club = None
        if mode == 'suggest' or who == 'club':
            m = ClubMembership.objects.filter(user=user, club_id=d.get('club')).select_related('club').first()
            if not m:
                return _bad('not_a_member', 'Pick a club you’re in.')
            club = m.club
        fields = dict(title=title[:200], activity_type=act, start=start.isoformat(), meeting_spot=spot[:200],
                      route=route.id if route else None, pace=pace, no_drop=bool(d.get('no_drop', True)),
                      capacity=cap, who_can_join=who)

        if mode == 'suggest':
            s = RideSuggestion.objects.create(member=user, club=club, proposal=fields, note=(d.get('note') or '')[:500])
            return Response({'mode': 'suggest', 'suggestion': s.id, 'club': club.name, 'status': 'new',
                             'summary': summary(fields, route, user)}, status=status.HTTP_201_CREATED)

        # Community ride: Plus only, host agreement once (requirements).
        if user.plan != 'plus':
            return _bad('plus_required', 'Hosting community rides is part of Plus.', status.HTTP_402_PAYMENT_REQUIRED)
        if not user.host_agreed_at:
            if not d.get('agree'):
                return _bad('agreement_required', 'Agree to the host agreement first.', status.HTTP_409_CONFLICT)
            user.host_agreed_at = timezone.now()
            user.save(update_fields=['host_agreed_at'])
        with transaction.atomic():
            e = create_event(fields, host=user, club=club if who == 'club' else None, kind='community', leader=user)
            EventRSVP.objects.get_or_create(event=e, user=user, defaults={'status': 'going'})
        from apps.chats.models import Chat
        chat = Chat.objects.filter(event=e).first()
        return Response({'mode': 'community', 'event': community.browse_card(e, user, request),
                         'chat': chat.id if chat else None,
                         'summary': summary(fields, route, user)}, status=status.HTTP_201_CREATED)


def create_event(fields, host, club, kind, leader):
    route = Route.objects.filter(pk=fields.get('route')).first() if fields.get('route') else None
    start = datetime.fromisoformat(fields['start'])
    return Event.objects.create(
        title=fields['title'], description='', host=host,
        host_name=club.name if club else person(host)['name'], vibe='Social', start_time=start,
        location_name=fields['meeting_spot'], location_address=fields['meeting_spot'],
        max_attendees=fields['capacity'], club=club, leader=leader, activity_type=fields['activity_type'],
        distance_m=route.distance_m if route else None, route=route, route_name=route.name if route else '',
        pace=community.PACE_LABELS[fields['pace']], no_drop=fields['no_drop'],
        level=community.PACE_LEVEL[fields['pace']], who_can_join=fields['who_can_join'], kind=kind,
    )


def approve_suggestion(s, reviewer):
    """Club team (portal, Phase 10; Django admin for now): approved becomes a
    club event with the member as ride leader."""
    m = ClubMembership.objects.filter(club=s.club, user=reviewer).first()
    if not (reviewer.is_staff or (m and m.can('approve_suggestions'))):
        raise PermissionError('Not allowed to approve suggestions for this club')
    with transaction.atomic():
        e = create_event(s.proposal, host=s.member, club=s.club, kind='club', leader=s.member)
        EventRSVP.objects.get_or_create(event=e, user=s.member, defaults={'status': 'going'})
        s.status, s.reviewed_by, s.event = 'approved', reviewer, e
        s.save()
        ClubTeamLog.objects.create(club=s.club, actor=reviewer, action=f'Approved ride suggestion “{e.title}”')
    return e


def summary(fields, route, user):
    tz = safe_zone(user.timezone)
    start = datetime.fromisoformat(fields['start']).astimezone(tz)
    route_bit = f'{route.name} · {route.distance_m / 1609.344:.1f} mi' if route else 'No set route'
    who = {'club': 'Club members', 'anyone': 'Anyone', 'invite': 'Invite only'}[fields['who_can_join']]
    return {
        'weekday': start.strftime('%a').upper(),
        'day': start.day,
        'title': fields['title'],
        'meta': f"{start.strftime('%a %b %-d')} · {start.strftime('%-I:%M %p')} · {fields['meeting_spot']}",
        'meta2': f"{route_bit} · {fields['pace'].capitalize()}{', no-drop' if fields['no_drop'] else ''}"
                 f" · {fields['capacity']} spots · {who}",
    }


class BuddiesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        flt = request.query_params.get('filter') or None
        items = community.buddy_suggestions(request.user, request, flt)
        my_next = (Event.objects.filter(rsvps__user=request.user, rsvps__status='going',
                                        start_time__gte=timezone.now(), is_cancelled=False)
                   .order_by('start_time').first())
        tz = safe_zone(request.user.timezone)
        return Response({
            'items': items,
            'my_next_event': ({'id': my_next.id, 'title': my_next.title,
                               'day': my_next.start_time.astimezone(tz).strftime('%A')} if my_next else None),
            'has_location': request.user.approx_lat is not None,
        })


class BuddyHideView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        get_object_or_404(User, pk=pk)
        Hide.objects.get_or_create(member=request.user, kind='not_interested', target_user_id=pk)
        return Response({'hidden': True})

    def delete(self, request, pk):
        Hide.objects.filter(member=request.user, kind='not_interested', target_user_id=pk).delete()
        return Response({'hidden': False})


class BuddyInviteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        other = get_object_or_404(User, pk=pk, is_active=True)
        from apps.safety.visibility import is_blocked
        if is_blocked(request.user, other.id):
            return _bad('not_found', 'Not found.', status.HTTP_404_NOT_FOUND)
        event = Event.objects.filter(pk=request.data.get('event'), rsvps__user=request.user,
                                     rsvps__status='going', start_time__gte=timezone.now()).first()
        if not event:
            return _bad('event', 'RSVP to a ride first, then invite people to it.')
        RideInvite.objects.get_or_create(sender=request.user, recipient=other, event=event)
        return Response({'invited': True, 'event': event.title})

    def delete(self, request, pk):
        RideInvite.objects.filter(sender=request.user, recipient_id=pk).delete()
        return Response({'invited': False})


class LocationView(APIView):
    """Approximate location for Fit Buddies distances. Rounded to about
    1 km before it's stored."""

    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        try:
            lat, lng = float(request.data['latitude']), float(request.data['longitude'])
        except (KeyError, TypeError, ValueError):
            return _bad('invalid', 'latitude and longitude are required.')
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return _bad('invalid', 'That location is out of range.')
        u = request.user
        u.approx_lat, u.approx_lng = round(lat, 2), round(lng, 2)
        u.save(update_fields=['approx_lat', 'approx_lng'])
        return Response({'ok': True})

    def delete(self, request):
        u = request.user
        u.approx_lat = u.approx_lng = None
        u.save(update_fields=['approx_lat', 'approx_lng'])
        return Response(status=status.HTTP_204_NO_CONTENT)
