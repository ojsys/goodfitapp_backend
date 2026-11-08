"""
Record -> Save -> Activity detail (Phase 2).

POST /api/activities/record/        save a recording (idempotent on client_id)
GET  /api/activities/<id>/detail/   detail as the viewer may see it
PATCH/DELETE /api/activities/<id>/detail/   owner edits title/effort/visibility, deletes
POST /api/activities/<id>/photos/   add a photo (owner)

The app saves every recording on the device first and retries the upload
until it succeeds, so the same `client_id` may arrive more than once.

Track points: {"lat", "lng", "alt" (m, optional), "t" (epoch ms), "seg" (int)}.
`seg` increases after each pause; distance and time never bridge two segments.
"""

from datetime import datetime, timezone as dt_tz

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.social.feed import activity_item
from apps.social.models import ClubMembership
from apps.social.privacy import can_view_activity, haversine_m, sample, visible_range

from .models import Activity, ActivityPhoto

MAX_POINTS = 20000
UNIT_M = {'mi': 1609.344, 'km': 1000.0}
PROFILE_SAMPLES = 120
DETAIL_TRACK_POINTS = 1500


def _bad(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({'code': code, 'message': message}, status=http)


def clean_points(raw):
    pts = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        try:
            lat, lng = float(p['lat']), float(p['lng'])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue
        alt = p.get('alt')
        pts.append({
            'lat': lat, 'lng': lng,
            'alt': float(alt) if isinstance(alt, (int, float)) else None,
            't': int(p['t']) if isinstance(p.get('t'), (int, float)) else None,
            'seg': int(p.get('seg') or 0),
        })
    return pts


def _smoothed_alts(pts, window=5):
    alts = [p['alt'] for p in pts]
    out = []
    for i in range(len(alts)):
        win = [a for a in alts[max(0, i - window // 2): i + window // 2 + 1] if a is not None]
        out.append(sum(win) / len(win) if win else None)
    return out


def track_stats(pts):
    """Distance (m), elevation gain (m), cumulative distance per point."""
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        step = haversine_m((a['lat'], a['lng']), (b['lat'], b['lng'])) if a['seg'] == b['seg'] else 0.0
        cum.append(cum[-1] + step)
    alts = _smoothed_alts(pts)
    gain, last = 0.0, None
    for a in alts:
        if a is None:
            continue
        if last is not None and a - last > 0.5:  # ignore GPS altitude jitter
            gain += a - last
            last = a
        elif last is None or a < last:
            last = a
    return cum[-1] if cum else 0.0, gain, cum, alts


def splits(pts, cum, alts, unit_m):
    """[{n, distance, time, elev}] per mile/km; the last one may be partial."""
    if len(pts) < 2 or not all(p['t'] for p in pts):
        return []
    out, n, start_i, moving = [], 1, 0, 0.0
    for i in range(1, len(pts)):
        if pts[i]['seg'] == pts[i - 1]['seg']:
            moving += (pts[i]['t'] - pts[i - 1]['t']) / 1000
        if cum[i] >= n * unit_m or i == len(pts) - 1:
            d = cum[i] - cum[start_i]
            if d < unit_m * 0.1 and out:  # tiny tail, fold into nothing
                break
            a0 = next((a for a in alts[start_i:i + 1] if a is not None), None)
            a1 = next((a for a in reversed(alts[start_i:i + 1]) if a is not None), None)
            out.append({'n': n, 'distance': d, 'time': round(moving),
                        'elev': round(a1 - a0, 1) if a0 is not None and a1 is not None else None})
            n, start_i, moving = n + 1, i, 0.0
    return out


def profile(pts, cum, alts, vis):
    """Elevation profile samples. `i` indexes the visible track (null where
    the viewer can't see the map position)."""
    if len(pts) < 2:
        return []
    i0, i1 = vis
    idx = [round(k * (len(pts) - 1) / (PROFILE_SAMPLES - 1)) for k in range(PROFILE_SAMPLES)] \
        if len(pts) > PROFILE_SAMPLES else list(range(len(pts)))
    return [{'d': round(cum[k], 1), 'e': round(alts[k], 1) if alts[k] is not None else None,
             'p': [round(pts[k]['lat'], 6), round(pts[k]['lng'], 6)] if i0 <= k < i1 else None}
            for k in idx]


class RecordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        d = request.data
        user = request.user
        kind = Activity.LEGACY_TYPES.get(d.get('type'), d.get('type'))
        if kind not in dict(Activity.ACTIVITY_TYPES) or kind == 'swim':
            return _bad('invalid_type', 'Pick an activity type.')
        client_id = d.get('client_id')
        if client_id:
            existing = Activity.objects.filter(user=user, client_id=client_id).first()
            if existing:
                return Response(self._detail(existing, request), status=status.HTTP_200_OK)
        try:
            start = datetime.fromisoformat(d['start_time'])
            if start.tzinfo is None:
                start = start.replace(tzinfo=dt_tz.utc)
            elapsed = int(d.get('elapsed_time') or 0)
            moving = int(d.get('moving_time') or elapsed)
        except (KeyError, ValueError, TypeError):
            return _bad('invalid', 'start_time and times are required.')
        if moving < 0 or elapsed < 0 or moving > elapsed + 1:
            return _bad('invalid', 'Times don’t add up.')

        raw = d.get('track') or []
        if len(raw) > MAX_POINTS:
            return _bad('too_long', 'That track is too long to upload.')
        pts = clean_points(raw) if kind in Activity.GPS_TYPES else []
        distance, gain, _, _ = track_stats(pts) if pts else (float(d.get('distance') or 0), 0.0, None, None)
        if d.get('elevation_gain') is not None and not pts:
            gain = float(d['elevation_gain'])

        visibility = d.get('visibility', 'followers')
        if visibility not in dict(Activity.VISIBILITY_CHOICES):
            return _bad('invalid_visibility', 'Pick who can see this.')
        club = None
        if visibility == 'club':
            m = ClubMembership.objects.filter(user=user, club_id=d.get('club')).select_related('club').first()
            if not m:
                return _bad('not_a_member', 'You can only share with a club you’re in.')
            club = m.club
        effort = d.get('effort')
        if effort is not None and effort not in range(5):
            return _bad('invalid_effort', 'Effort is 0 to 4.')
        title = (d.get('title') or '').strip()[:200] or 'Activity'
        route_ref = None
        if d.get('route'):
            from apps.routes.views import visible_routes
            route_ref = visible_routes(user).filter(pk=d['route']).first()

        max_speed = d.get('max_speed')
        max_speed = float(max_speed) if isinstance(max_speed, (int, float)) else None

        try:
            with transaction.atomic():
                act = Activity.objects.create(
                    user=user, type=kind, title=title, start_time=start,
                    end_time=datetime.fromtimestamp(start.timestamp() + elapsed, tz=dt_tz.utc),
                    duration=round(moving / 60), moving_time=moving, elapsed_time=elapsed,
                    distance=distance, elevation_gain=gain, max_speed=max_speed,
                    average_speed=(distance / 1000) / (moving / 3600) if moving and distance else None,
                    calories_burned=d.get('calories') if isinstance(d.get('calories'), int) else None,
                    effort=effort, visibility=visibility, club=club,
                    laps=d.get('laps') if isinstance(d.get('laps'), list) else [],
                    route_name=(d.get('route_name') or (route_ref.name if route_ref else ''))[:120],
                    route_ref=route_ref,
                    route=pts, client_id=client_id or None,
                    start_latitude=pts[0]['lat'] if pts else None,
                    start_longitude=pts[0]['lng'] if pts else None,
                )
        except IntegrityError:
            act = Activity.objects.get(user=user, client_id=client_id)
            return Response(self._detail(act, request), status=status.HTTP_200_OK)
        return Response(self._detail(act, request), status=status.HTTP_201_CREATED)

    @staticmethod
    def _detail(act, request):
        return detail(act, request.user, request)


def detail(act, viewer, request=None):
    item = activity_item(act, viewer, request, preview=False)
    pts = clean_points(act.route) if act.is_gps else []
    if not pts and act.is_gps:
        # Older records stored {latitude, longitude}.
        pts = [{'lat': p[0], 'lng': p[1], 'alt': p[2] if isinstance(p[2], (int, float)) else None,
                't': None, 'seg': 0} for p in act.track_points()]
    owner = viewer.id == act.user_id
    vis = (0, len(pts)) if owner else visible_range([(p['lat'], p['lng']) for p in pts], act.user)
    track = [[round(p['lat'], 6), round(p['lng'], 6)] for p in pts[vis[0]:vis[1]]]
    _, _, cum, alts = track_stats(pts) if pts else (0, 0, [], [])
    unit = viewer.units if viewer.units in UNIT_M else 'mi'
    item.update({
        'elapsed_time': act.elapsed_time,
        'avg_speed': act.average_speed,
        'max_speed': act.max_speed,
        'avg_power': act.avg_power,
        'cadence': act.cadence,
        'heart_rate_avg': act.heart_rate_avg,
        'calories': act.calories_burned,
        'effort': act.effort,
        'laps': act.laps or [],
        'club_id': act.club_id,
        'track': sample(track, DETAIL_TRACK_POINTS),
        'profile': profile(pts, cum, alts, vis) if pts else [],
        'splits': splits(pts, cum, alts, UNIT_M[unit]) if pts else [],
        'split_unit': unit,
    })
    return item


class ActivityDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        act = get_object_or_404(Activity.objects.select_related('user'), pk=pk)
        if not can_view_activity(request.user, act):
            return _bad('not_found', 'Not found.', status.HTTP_404_NOT_FOUND)
        return Response(detail(act, request.user, request))

    def patch(self, request, pk):
        act = get_object_or_404(Activity, pk=pk, user=request.user)
        d = request.data
        if 'title' in d:
            title = (d.get('title') or '').strip()
            if not title:
                return _bad('invalid', 'Give it a title.')
            act.title = title[:200]
        if 'effort' in d:
            if d['effort'] is not None and d['effort'] not in range(5):
                return _bad('invalid_effort', 'Effort is 0 to 4.')
            act.effort = d['effort']
        if 'visibility' in d:
            if d['visibility'] not in dict(Activity.VISIBILITY_CHOICES):
                return _bad('invalid_visibility', 'Pick who can see this.')
            act.visibility = d['visibility']
            if act.visibility == 'club':
                m = ClubMembership.objects.filter(user=request.user, club_id=d.get('club')).first()
                if not m:
                    return _bad('not_a_member', 'You can only share with a club you’re in.')
                act.club_id = m.club_id
        act.save()
        return Response(detail(act, request.user, request))

    def delete(self, request, pk):
        act = get_object_or_404(Activity, pk=pk, user=request.user)
        act.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ActivityPhotoView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    MAX_PHOTOS = 10

    def post(self, request, pk):
        act = get_object_or_404(Activity, pk=pk, user=request.user)
        image = request.FILES.get('image')
        if not image:
            return _bad('missing', 'Attach an image.')
        if act.photos.count() >= self.MAX_PHOTOS:
            return _bad('too_many', f'Up to {self.MAX_PHOTOS} photos per activity.')
        ph = ActivityPhoto.objects.create(activity=act, image=image)
        return Response({'id': ph.id, 'url': request.build_absolute_uri(ph.image.url)},
                        status=status.HTTP_201_CREATED)
