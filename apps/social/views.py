"""
Home, feed, posts, props, comments, clubs and people (Phase 2).
All endpoints require a full member (MemberJWTAuthentication default).
"""

from apps.business.services import featured_for
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.activities.models import Activity
from apps.users.models import User

from . import feed, home
from .models import Club, ClubMembership, Comment, Follow, Post, PrivacyZone, Prop, Wave
from apps.safety.visibility import blocked_ids, is_blocked

from .privacy import can_view_activity, can_view_post


def _bad(code, message, http=status.HTTP_400_BAD_REQUEST):
    return Response({'code': code, 'message': message}, status=http)


class HomeView(APIView):
    """Everything Home needs besides the feed, in one call (first paint)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        cl = home.checklist(user)
        data = {
            'me': feed.person(user, request),
            'units': user.units,
            'counts': home.header_counts(user),
            'week': home.week(user),
            'checklist': cl,
            'upcoming_ride': home.upcoming_group_ride(user, request),
            # A featured event (Boost and Partner): a card in Home feeds.
            'featured': featured_for(user, 'home', request),
            # The club you help run first, then the one you joined first.
            'my_clubs': [home.club_card(m.club, user) for m in sorted(
                ClubMembership.objects.filter(user=user).select_related('club'),
                key=lambda m: (m.role == 'member', m.joined_at))],
        }
        if cl['new_member_home'] or not data['my_clubs']:
            # Also feeds the Club tab's empty state ("Join GoodCo Bike Club").
            data['clubs_near_you'] = home.suggested_clubs(user)
        if cl['new_member_home']:
            data['first_ride'] = home.first_ride(user, request)
            data['people'] = home.suggested_people(user, request)
        return Response(data)


class FeedView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        tab = request.query_params.get('tab', 'following')
        if tab not in ('following', 'club', 'mine'):
            return _bad('invalid_tab', 'Unknown feed tab.')
        before = feed.parse_before(request.query_params.get('before'))
        return Response(feed.page(request.user, tab, before, request))


class ChecklistView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        hidden = request.data.get('hidden')
        if not isinstance(hidden, bool):
            return _bad('invalid', 'hidden must be true or false.')
        request.user.checklist_hidden = hidden
        request.user.save(update_fields=['checklist_hidden'])
        return Response(home.checklist(request.user))


# ------------------------------------------------------------------- posts

class PostCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        d = request.data
        ptype = d.get('type', 'moment')
        if ptype not in dict(Post.TYPES):
            return _bad('invalid_type', 'Pick Moment, Check-in or Shoutout.')
        text = (d.get('text') or '').strip()
        if len(text) > Post.MAX_TEXT:
            return _bad('too_long', f'Keep it under {Post.MAX_TEXT} characters.')
        mood = d.get('mood') or ''
        if mood and (ptype != 'checkin' or mood not in dict(Post.MOODS)):
            return _bad('invalid_mood', 'Moods go with a check-in.')
        photo = request.FILES.get('photo')
        # "Post enables once there is text, a photo or a mood."
        if not (text or photo or mood):
            return _bad('empty', 'Add some text, a photo or a mood.')
        audience = d.get('audience', 'followers')
        if audience not in dict(Post.AUDIENCES):
            return _bad('invalid_audience', 'Pick who can see this.')
        club = None
        if audience == 'club':
            club = Club.objects.filter(id=d.get('club'), memberships__user=request.user).first()
            if not club:
                return _bad('not_a_member', 'You can only post to a club you’re in.')
        tagged_ids = d.getlist('tagged') if hasattr(d, 'getlist') else (d.get('tagged') or [])
        is_intro = str(d.get('is_intro', '')).lower() in ('1', 'true')

        post = Post.objects.create(
            author=request.user, type=ptype, text=text, mood=mood if ptype == 'checkin' else '',
            photo=photo, audience=audience, club=club, is_intro=is_intro,
        )
        if tagged_ids:
            # Only people you follow or share a club with can be tagged.
            allowed = User.objects.filter(id__in=tagged_ids).filter(
                id__in=_crew_ids(request.user)).exclude(id__in=blocked_ids(request.user))
            post.tagged.set(allowed)
        toast = feed.AUDIENCE_TOAST.get(audience) or f'Posted to {club.name}'
        return Response({'item': feed.post_item(post, request.user, request), 'toast': toast},
                        status=status.HTTP_201_CREATED)


class PostDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        post = get_object_or_404(Post, pk=pk)
        if post.author_id != request.user.id:
            return _bad('forbidden', 'You can only delete your own posts.', status.HTTP_403_FORBIDDEN)
        post.delete()  # props and comments go with it
        return Response(status=status.HTTP_204_NO_CONTENT)


def _crew_ids(user):
    followees = Follow.objects.filter(follower=user).values_list('followee_id', flat=True)
    clubs = ClubMembership.objects.filter(user=user).values('club_id')
    mates = ClubMembership.objects.filter(club_id__in=clubs).values_list('user_id', flat=True)
    return (set(followees) | set(mates)) - {user.id}


class CrewView(APIView):
    """People you can tag: who you follow and your club mates."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        q = (request.query_params.get('q') or '').strip()
        people = User.objects.filter(id__in=_crew_ids(request.user), is_active=True).exclude(
            id__in=blocked_ids(request.user))
        if q:
            people = people.filter(display_name__icontains=q) | people.filter(first_name__icontains=q)
        return Response([feed.person(u, request) for u in people.order_by('first_name', 'display_name')[:50]])


# ---------------------------------------------------- props and comments

def _target(kind, pk, user):
    """The post or activity, if the viewer may see it."""
    if kind not in ('posts', 'activities'):
        from django.http import Http404
        raise Http404
    if kind == 'posts':
        obj = get_object_or_404(Post, pk=pk)
        return obj if can_view_post(user, obj) else None
    obj = get_object_or_404(Activity, pk=pk)
    return obj if can_view_activity(user, obj) else None


def _fk(kind):
    return 'post' if kind == 'posts' else 'activity'


class PropsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, kind, pk):
        obj = _target(kind, pk, request.user)
        if obj is None:
            return _bad('not_found', 'Not found.', status.HTTP_404_NOT_FOUND)
        try:
            with transaction.atomic():
                Prop.objects.create(user=request.user, **{_fk(kind): obj})
        except IntegrityError:
            pass  # already given
        return Response({'props': obj.props.count(), 'propped': True})

    def delete(self, request, kind, pk):
        obj = _target(kind, pk, request.user)
        if obj is None:
            return _bad('not_found', 'Not found.', status.HTTP_404_NOT_FOUND)
        Prop.objects.filter(user=request.user, **{_fk(kind): obj}).delete()
        return Response({'props': obj.props.count(), 'propped': False})


def comment_item(c, request=None):
    return {
        'id': c.id,
        'author': feed.person(c.author, request),
        'text': c.text,
        'created_at': c.created_at.isoformat(),
        'is_mine': bool(request and c.author_id == request.user.id),
    }


class CommentsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, kind, pk):
        obj = _target(kind, pk, request.user)
        if obj is None:
            return _bad('not_found', 'Not found.', status.HTTP_404_NOT_FOUND)
        from apps.safety.visibility import blocked_ids
        qs = (obj.comments.exclude(author_id__in=blocked_ids(request.user)).filter(author__is_active=True)
              .select_related('author').order_by('created_at'))
        return Response({'count': qs.count(), 'items': [comment_item(c, request) for c in qs]})

    def post(self, request, kind, pk):
        obj = _target(kind, pk, request.user)
        if obj is None:
            return _bad('not_found', 'Not found.', status.HTTP_404_NOT_FOUND)
        text = (request.data.get('text') or '').strip()
        if not text:
            return _bad('empty', 'Write a comment first.')
        if len(text) > Comment.MAX_TEXT:
            return _bad('too_long', f'Keep it under {Comment.MAX_TEXT} characters.')
        c = Comment.objects.create(author=request.user, text=text, **{_fk(kind): obj})
        return Response(comment_item(c, request), status=status.HTTP_201_CREATED)


class CommentDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        c = get_object_or_404(Comment, pk=pk)
        owner_of_target = (c.post and c.post.author_id == request.user.id) or (
            c.activity and c.activity.user_id == request.user.id)
        if c.author_id != request.user.id and not owner_of_target:
            return _bad('forbidden', 'You can’t delete this comment.', status.HTTP_403_FORBIDDEN)
        c.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------- clubs and people

class ClubJoinView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        ClubMembership.objects.get_or_create(club=club, user=request.user)
        return Response(home.club_card(club, request.user))

    def delete(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        m = ClubMembership.objects.filter(club=club, user=request.user).first()
        if m and m.role == 'owner':
            return _bad('owner', 'Owners can’t leave their own club.')
        if m:
            m.delete()
        return Response(home.club_card(club, request.user))


class FollowView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if pk == request.user.id:
            return _bad('self', 'You can’t follow yourself.')
        other = get_object_or_404(User, pk=pk, is_active=True)
        if is_blocked(request.user, other.id):
            return _bad('not_found', 'Not found.', status.HTTP_404_NOT_FOUND)
        Follow.objects.get_or_create(follower=request.user, followee=other)
        return Response({'following': True})

    def delete(self, request, pk):
        Follow.objects.filter(follower=request.user, followee_id=pk).delete()
        return Response({'following': False})


class WaveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if pk == request.user.id:
            return _bad('self', 'You can’t wave at yourself.')
        other = get_object_or_404(User, pk=pk, is_active=True)
        if is_blocked(request.user, other.id):
            return _bad('not_found', 'Not found.', status.HTTP_404_NOT_FOUND)
        Wave.objects.get_or_create(sender=request.user, recipient=other)
        return Response({'waved': True})

    def delete(self, request, pk):
        Wave.objects.filter(sender=request.user, recipient_id=pk).delete()
        return Response({'waved': False})


# ----------------------------------------------------------- privacy zones

def zone_item(z):
    return {'id': z.id, 'label': z.label, 'latitude': z.latitude, 'longitude': z.longitude, 'radius_m': z.radius_m}


class PrivacyZonesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({
            'hide_track_ends': request.user.hide_track_ends,
            'zones': [zone_item(z) for z in request.user.privacy_zones.all()],
        })

    def post(self, request):
        d = request.data
        try:
            lat, lng = float(d['latitude']), float(d['longitude'])
        except (KeyError, TypeError, ValueError):
            return _bad('invalid', 'latitude and longitude are required.')
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return _bad('invalid', 'That location is out of range.')
        radius = int(d.get('radius_m') or 400)
        if not 100 <= radius <= 1600:
            return _bad('invalid', 'Radius must be between 100 and 1600 meters.')
        label = d.get('label', 'home')
        if label not in dict(PrivacyZone.LABELS):
            return _bad('invalid', 'Label must be home, work or other.')
        z = PrivacyZone.objects.create(user=request.user, label=label, latitude=lat, longitude=lng, radius_m=radius)
        return Response(zone_item(z), status=status.HTTP_201_CREATED)

    def patch(self, request):
        v = request.data.get('hide_track_ends')
        if not isinstance(v, bool):
            return _bad('invalid', 'hide_track_ends must be true or false.')
        request.user.hide_track_ends = v
        request.user.save(update_fields=['hide_track_ends'])
        return self.get(request)


class PrivacyZoneDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        PrivacyZone.objects.filter(user=request.user, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
