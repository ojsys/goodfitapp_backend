"""
GET  /api/performance/segments/<id>/?scope=all|year|club|following   the segment page
GET  /api/performance/segments/nearby/?lat=&lng=                      for live alerts while recording
POST /api/performance/preview/   {type, track}                        PRs before saving (Save screen)
GET  /api/performance/challenges/                                     featured, running, browse, trophies
POST/DELETE /api/performance/challenges/<id>/join/
GET  /api/performance/training/?range=week|month|year|all&sport=ride|run
"""

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import challenges, segments, training
from .models import Challenge, ChallengeEntry, Segment


def _bad(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({'code': code, 'message': message}, status=http)


class SegmentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        seg = get_object_or_404(Segment, pk=pk, is_active=True)
        scope = request.query_params.get('scope') or 'all'
        if scope not in ('all', 'year', 'club', 'following'):
            return _bad('scope', 'Pick all, year, club or following.')
        return Response(segments.segment_page(seg, request.user, scope, request))


class NearbyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            lat, lng = float(request.query_params['lat']), float(request.query_params['lng'])
        except (KeyError, ValueError):
            return _bad('invalid', 'lat and lng are required.')
        return Response({'items': segments.nearby(lat, lng, request.user)})


class PreviewView(APIView):
    """What the Save screen shows before upload: 'New PR on Zoo Hill'."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from apps.activities.record_views import MAX_POINTS, clean_points
        kind = request.data.get('type')
        raw = request.data.get('track') or []
        if kind not in ('ride', 'run') or len(raw) > MAX_POINTS:
            return Response({'items': []})
        pts = [(p['lat'], p['lng'], p.get('alt'), p.get('t')) for p in clean_points(raw)]
        return Response({'items': segments.achievements(kind, pts, request.user)})


class ChallengesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Anything finished since the last upload (or by a backfill) gets its trophy now.
        challenges.update_for(request.user)
        return Response(challenges.page(request.user, request))


class JoinView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        ch = get_object_or_404(challenges.visible_to(request.user), pk=pk)
        ChallengeEntry.objects.get_or_create(challenge=ch, user=request.user)
        challenges.update_for(request.user)
        return Response(challenges.page(request.user, request))

    def delete(self, request, pk):
        ChallengeEntry.objects.filter(challenge_id=pk, user=request.user, completed_at__isnull=True).delete()
        return Response(challenges.page(request.user, request))


class TrainingView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        kind = request.query_params.get('range') or 'week'
        if kind not in ('week', 'month', 'year', 'all'):
            return _bad('range', 'Pick week, month, year or all.')
        sport = request.query_params.get('sport') or None
        if sport not in (None, 'ride', 'run', 'all'):
            return _bad('sport', 'Pick ride, run or all.')
        return Response(training.page(request.user, kind, None if sport == 'all' else sport, request))
