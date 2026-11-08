"""
Profiles (You-Profile, and other members' profiles).

GET /api/social/me/profile/                  the You screen
GET /api/social/people/<id>/                 someone's profile, as the viewer may see it
GET /api/social/people/<id>/followers/       and /following/
"""

from datetime import datetime, time, timedelta

from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.activities.models import Activity
from apps.goodmatch.services import new_today
from apps.safety.visibility import blocked_ids, is_blocked
from apps.users.age_gate import safe_zone
from apps.users.models import User

from .feed import activity_item, person
from .models import ClubMembership, Follow, Wave
from .privacy import visible_activities_q

MI = 1609.344


def season(acts, user):
    """This calendar year so far."""
    tz = safe_zone(user.timezone)
    now = timezone.localtime(timezone.now(), tz)
    start = datetime.combine(now.date().replace(month=1, day=1), time.min, tzinfo=tz)
    agg = acts.filter(start_time__gte=start).aggregate(n=Count('id'), d=Sum('distance'), e=Sum('elevation_gain'),
                                                       t=Sum('moving_time'))
    return {
        'label': f'{now.year} Season',
        'range': f'Jan – {now:%b}' if now.month > 1 else 'January',
        'activities': agg['n'] or 0,
        'distance': agg['d'] or 0,
        'elevation_gain': agg['e'] or 0,
        'moving_time': agg['t'] or 0,
    }


def training(user):
    """This week's distance and the run of weeks with at least one activity."""
    tz = safe_zone(user.timezone)
    today = timezone.localtime(timezone.now(), tz).date()
    monday = today - timedelta(days=today.weekday())
    starts = Activity.objects.filter(user=user, start_time__gte=datetime.combine(
        monday - timedelta(weeks=104), time.min, tzinfo=tz)).values_list('start_time', 'distance')
    weeks, this_week = set(), 0
    for st, dist in starts:
        d = timezone.localtime(st, tz).date()
        wk = d - timedelta(days=d.weekday())
        weeks.add(wk)
        if wk == monday:
            this_week += dist or 0
    streak, wk = 0, monday if monday in weeks else monday - timedelta(weeks=1)
    while wk in weeks:
        streak += 1
        wk -= timedelta(weeks=1)
    return {'this_week': this_week, 'streak_weeks': streak}


def _counts(u):
    return {'following': Follow.objects.filter(follower=u, followee__is_active=True).count(),
            'followers': Follow.objects.filter(followee=u, follower__is_active=True).count()}


def share_url(path):
    from django.conf import settings
    return f'{settings.SHARE_BASE_URL.rstrip("/")}{path}'


def _top_challenge(user, request):
    from apps.performance import challenges
    data = challenges.page(user, request)
    joined = ([data['featured']] if data['featured'] and data['featured']['joined'] else []) + data['running']
    return {**joined[0], 'more': len(joined) - 1} if joined else None


def _trophies(user):
    from apps.performance.models import Trophy
    tz = safe_zone(user.timezone)
    return {'count': Trophy.objects.filter(user=user).count(),
            'items': [{'label': t.label, 'month': timezone.localtime(t.earned_at, tz).strftime('%b')}
                      for t in Trophy.objects.filter(user=user)[:4]]}


class MyProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        u = request.user
        mine = Activity.objects.filter(user=u)
        recent = mine.order_by('-start_time')[:3]
        from apps.routes.models import RouteSave
        return Response({
            'person': person(u, request),
            'neighborhood': u.neighborhood,
            'headline': u.headline,
            'interests': u.interests or [],
            **_counts(u),
            'season': season(mine, u),
            'training': training(u),
            'saved_routes': RouteSave.objects.filter(user=u).count(),
            'challenge': _top_challenge(u, request),
            'trophies': _trophies(u),
            'match': {'show': u.match_opted_in, 'new_today': new_today(u) if u.match_opted_in else 0},
            'recent': [activity_item(a, u, request, preview=False) for a in recent],
            'share_url': share_url(f'/u/{u.id}'),
        })


class PersonView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        viewer = request.user
        u = get_object_or_404(User, pk=pk, is_active=True)
        if is_blocked(viewer, u.id):
            return Response({'code': 'not_found', 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        acts = Activity.objects.filter(user=u).filter(visible_activities_q(viewer))
        recent = acts.order_by('-start_time')[:5]
        shared_clubs = (ClubMembership.objects.filter(user=u, club__memberships__user=viewer)
                        .select_related('club').distinct())
        return Response({
            'person': person(u, request),
            'is_me': u.id == viewer.id,
            'neighborhood': u.neighborhood,
            'headline': u.headline,
            'bio': u.bio,
            'interests': u.interests or [],
            **_counts(u),
            'is_following': Follow.objects.filter(follower=viewer, followee=u).exists(),
            'follows_you': Follow.objects.filter(follower=u, followee=viewer).exists(),
            'waved': Wave.objects.filter(sender=viewer, recipient=u).exists(),
            'clubs': [{'id': m.club_id, 'name': m.club.name} for m in shared_clubs],
            'season': season(acts, u),
            'recent': [activity_item(a, viewer, request, preview=False) for a in recent],
            'share_url': share_url(f'/u/{u.id}'),
        })


class FollowListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    which = 'followers'

    def get(self, request, pk):
        u = get_object_or_404(User, pk=pk, is_active=True)
        if is_blocked(request.user, u.id):
            return Response({'code': 'not_found', 'message': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        hidden = blocked_ids(request.user)
        if self.which == 'followers':
            people = [f.follower for f in Follow.objects.filter(followee=u, follower__is_active=True)
                      .exclude(follower_id__in=hidden).select_related('follower').order_by('-created_at')[:200]]
        else:
            people = [f.followee for f in Follow.objects.filter(follower=u, followee__is_active=True)
                      .exclude(followee_id__in=hidden).select_related('followee').order_by('-created_at')[:200]]
        mine = set(Follow.objects.filter(follower=request.user).values_list('followee_id', flat=True))
        return Response({'items': [dict(person(p, request), is_following=p.id in mine, is_me=p.id == request.user.id)
                                   for p in people]})
