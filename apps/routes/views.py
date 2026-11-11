"""
Routes list, map, save, create and snap (Community-Routes, -CreateRoute).

GET    /api/routes/?type=ride|run|walk|hike&filter=under5|flat|saved&q=
POST   /api/routes/                     create (snapped line + stats)
POST   /api/routes/snap/                preview a line for the drawn points
POST/DELETE /api/routes/<id>/save/
GET    /api/routes/<id>/
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.activities.models import Activity
from apps.events.models import Event
from apps.social.feed import person
from apps.social.models import ClubMembership

from .models import Route, RouteSave
from .services import elevation_gain, est_minutes, line_distance, snap

MI = 1609.344
FLAT_M_PER_KM = 8  # "Flat": under 8 m of climb per km


def _bad(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({'code': code, 'message': message}, status=http)


def saved_routes(user):
    """Saved Routes on You and the Saved chip: the same list and count."""
    return visible_routes(user).filter(saves__user=user)


def visible_routes(user):
    clubs = ClubMembership.objects.filter(user=user).values('club_id')
    return Route.objects.filter(Q(owner=user) | Q(visibility='public') | Q(visibility='club', club_id__in=clubs))


def route_card(route, user, request=None, line_points=120):
    from apps.social.privacy import sample
    week_ago = timezone.now() - timedelta(days=7)
    my_clubs = ClubMembership.objects.filter(user=user).values('club_id')
    mates = ClubMembership.objects.filter(club_id__in=my_clubs).exclude(user=user).values('user_id')
    recent = (Activity.objects.filter(route_ref=route, start_time__gte=week_ago, user_id__in=mates)
              .select_related('user').order_by('-start_time'))
    mate_people, seen = [], set()
    for a in recent:
        if a.user_id not in seen:
            seen.add(a.user_id)
            mate_people.append(person(a.user, request))
    riders = Activity.objects.filter(route_ref=route).values('user_id').distinct().count()
    used_by = (Event.objects.filter(route=route, is_active=True, is_cancelled=False, start_time__gte=timezone.now())
               .order_by('start_time').first())
    return {
        'id': route.id,
        'name': route.name,
        'best_for': route.best_for,
        'is_loop': route.is_loop,
        'surface': route.get_surface_display(),
        'riders': riders,
        'distance': route.distance_m,
        'elevation_gain': route.elevation_gain_m,
        'est_minutes': est_minutes(route.distance_m, route.best_for, user),
        'line': sample(route.line, line_points),
        'visibility': route.visibility,
        'club_favorite': route.club_favorite,
        'club_mates_this_week': len(mate_people),
        'club_mates': mate_people[:3],
        'used_by_event': {'id': used_by.id, 'title': used_by.title} if used_by else None,
        'saved': RouteSave.objects.filter(user=user, route=route).exists(),
        'is_mine': route.owner_id == user.id,
    }


class RoutesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        qs = visible_routes(user)
        t = request.query_params.get('type')
        if t in dict(Route.BEST_FOR):
            qs = qs.filter(best_for=t)
        f = request.query_params.get('filter')
        if f == 'under5':
            qs = qs.filter(distance_m__lt=5 * MI)
        elif f == 'saved':
            qs = qs.filter(id__in=saved_routes(user).values('id'))
        q = (request.query_params.get('q') or '').strip()
        if q:
            qs = qs.filter(name__icontains=q)
        qs = qs.annotate(n=Count('activities', distinct=True)).order_by('-club_favorite', '-n', '-created_at')[:50]
        cards = [route_card(r, user, request) for r in qs]
        if f == 'flat':
            cards = [c for c in cards if c['distance'] and c['elevation_gain'] / (c['distance'] / 1000) < FLAT_M_PER_KM]
        return Response({'items': cards})

    def post(self, request):
        user = request.user
        d = request.data
        name = (d.get('name') or '').strip()
        if len(name) < 2:
            return _bad('name', 'Name your route to save.')
        pts = _points(d.get('waypoints'))
        if len(pts) < 2:
            return _bad('points', 'Add at least 2 points.')
        best_for = d.get('best_for', 'ride')
        if best_for not in dict(Route.BEST_FOR):
            return _bad('best_for', 'Pick ride, run or walk.')
        visibility = d.get('visibility', 'public')
        if visibility not in dict(Route.VISIBILITY):
            return _bad('visibility', 'Pick who can see it.')
        club = None
        if visibility == 'club':
            m = ClubMembership.objects.filter(user=user, club_id=d.get('club')).select_related('club').first()
            if not m:
                return _bad('not_a_member', 'You can only share with a club you’re in.')
            club = m.club
        # Unlimited routes are part of Plus (requirements: Plans).
        if user.plan != 'plus' and Route.objects.filter(owner=user).count() >= settings.FREE_ROUTE_LIMIT:
            return _bad('plus_required', f'Free members can keep {settings.FREE_ROUTE_LIMIT} routes. '
                                         'Plus makes it unlimited.', status.HTTP_402_PAYMENT_REQUIRED)
        line = _points(d.get('line')) or pts
        if len(line) < 2:
            line = pts
        is_loop = bool(d.get('is_loop'))
        gain, _ = elevation_gain(line)
        r = Route.objects.create(owner=user, club=club, name=name[:120], best_for=best_for, line=line,
                                 waypoints=pts, distance_m=line_distance(line), elevation_gain_m=gain,
                                 is_loop=is_loop, visibility=visibility)
        # Your own routes start in Saved (You > Saved Routes, the Saved chip).
        RouteSave.objects.get_or_create(user=user, route=r)
        return Response(route_card(r, user, request), status=status.HTTP_201_CREATED)


def _points(raw):
    out = []
    for p in raw or []:
        try:
            lat, lng = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            out.append([round(lat, 6), round(lng, 6)])
    return out[:200]


class SnapView(APIView):
    """Live line, distance, climb and time while drawing."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        pts = _points(request.data.get('waypoints'))
        best_for = request.data.get('best_for', 'ride')
        if best_for not in dict(Route.BEST_FOR):
            best_for = 'ride'
        if request.data.get('is_loop') and len(pts) >= 2:
            pts = pts + [pts[0]]
        line, snapped = snap(pts, best_for)
        gain, has_elev = elevation_gain(line) if request.data.get('elevation', True) else (0.0, False)
        dist = line_distance(line)
        return Response({
            'line': line,
            'snapped': snapped,
            'distance': dist,
            'elevation_gain': gain,
            'has_elevation': has_elev,
            'est_minutes': est_minutes(dist, best_for, request.user) if dist else 0,
        })


class RouteDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        r = get_object_or_404(visible_routes(request.user), pk=pk)
        return Response(route_card(r, request.user, request, line_points=1000))

    def delete(self, request, pk):
        r = get_object_or_404(Route, pk=pk, owner=request.user)
        r.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RouteSaveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        r = get_object_or_404(visible_routes(request.user), pk=pk)
        RouteSave.objects.get_or_create(user=request.user, route=r)
        return Response({'saved': True})

    def delete(self, request, pk):
        RouteSave.objects.filter(user=request.user, route_id=pk).delete()
        return Response({'saved': False})
