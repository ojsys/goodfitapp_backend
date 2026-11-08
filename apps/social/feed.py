"""
Home feed (Core-Feed.dc.html): Following, Club and My Activity, merged from
posts and activities, newest first, paged with a `before` cursor.

Tabs:
- following: your own and the people you follow. Posts to Followers;
  activities visible to Everyone or Followers.
- club: posts to your clubs, club-only activities for your clubs, and
  activities members of your clubs shared with Everyone.
- mine: everything you posted or recorded, including Only me.
"""

from datetime import datetime

from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from apps.activities.models import Activity

from .models import ClubMembership, Follow, Post, Prop
from .privacy import track_for

PAGE = 20
PREVIEW_POINTS = 120

AUDIENCE_TOAST = {'followers': 'Posted to Following', 'me': 'Saved to My Activity'}


def person(user, request=None):
    name = user.full_name or user.display_name or user.email.split('@')[0]
    parts = [p for p in name.split() if p]
    initials = ''.join(p[0] for p in parts[:2]).upper() or name[:2].upper()
    return {
        'id': user.id,
        'name': name,
        'first_name': parts[0] if parts else name,
        'initials': initials,
        'photo': user.photo_url(request),
        'neighborhood': user.neighborhood,
    }


def _club_label(club):
    return club.name if club else 'Club'


def post_item(post, viewer, request=None):
    tagged = list(post.tagged.all())
    item = {
        'kind': 'post',
        'id': post.id,
        'sort': post.created_at.isoformat(),
        'created_at': post.created_at.isoformat(),
        'author': person(post.author, request),
        'is_mine': post.author_id == viewer.id,
        'type': post.type,
        'mood': post.mood or None,
        'text': post.text,
        'photo': request.build_absolute_uri(post.photo.url) if (post.photo and request) else (
            post.photo.url if post.photo else None),
        'tagged': [person(u, request) for u in tagged],
        'audience': post.audience,
        'audience_label': {'followers': 'Followers', 'me': 'Only me'}.get(post.audience) or _club_label(post.club),
        'club_id': post.club_id,
        'is_intro': post.is_intro,
        'props': post.n_props if hasattr(post, 'n_props') else post.props.count(),
        'comments': post.n_comments if hasattr(post, 'n_comments') else post.comments.count(),
        'propped': bool(getattr(post, 'i_propped', False)),
    }
    if post.is_intro or item['props']:
        from apps.safety.visibility import blocked_ids
        names = list(
            Prop.objects.filter(post=post).exclude(user_id__in=blocked_ids(viewer))
            .select_related('user').order_by('created_at')[:2]
        )
        item['props_by'] = [person(p.user, request)['first_name'] for p in names]
        item['props_initials'] = [person(p.user, request)['initials'] for p in names]
        item['props_ids'] = [p.user_id for p in names]
    return item


def activity_item(act, viewer, request=None, preview=True):
    item = {
        'kind': 'activity',
        'id': act.id,
        'sort': act.start_time.isoformat(),
        'created_at': act.start_time.isoformat(),
        'author': person(act.user, request),
        'is_mine': act.user_id == viewer.id,
        'type': act.type,
        'title': act.title,
        'distance': act.distance,
        'moving_time': act.moving_time if act.moving_time is not None else (act.duration or 0) * 60,
        'elevation_gain': act.elevation_gain,
        'location': act.start_address,
        'route_name': act.route_name,
        'visibility': act.visibility,
        'props': act.n_props if hasattr(act, 'n_props') else act.props.count(),
        'comments': act.n_comments if hasattr(act, 'n_comments') else act.comments.count(),
        'propped': bool(getattr(act, 'i_propped', False)),
        'photos': [request.build_absolute_uri(p.image.url) if request else p.image.url for p in act.photos.all()],
    }
    if preview:
        item['track'] = track_for(act, viewer, PREVIEW_POINTS) if act.is_gps else []
    return item


def _annotate_posts(qs, viewer):
    return qs.select_related('author', 'club').prefetch_related('tagged').annotate(
        n_props=Count('props', distinct=True),
        n_comments=Count('comments', distinct=True),
        i_propped=Exists(Prop.objects.filter(post=OuterRef('pk'), user=viewer)),
    )


def _annotate_acts(qs, viewer):
    return qs.select_related('user').prefetch_related('photos', 'user__privacy_zones').annotate(
        n_props=Count('props', distinct=True),
        n_comments=Count('comments', distinct=True),
        i_propped=Exists(Prop.objects.filter(activity=OuterRef('pk'), user=viewer)),
    )


def tab_querysets(viewer, tab):
    """(posts, activities) for a tab, unpaged. Never anyone blocked either
    way, nor anything the viewer hid or reported."""
    if tab == 'mine':
        return Post.objects.filter(author=viewer), Activity.objects.filter(user=viewer)
    from apps.safety.visibility import blocked_ids, hidden_activity_ids, hidden_post_ids
    posts, acts = _tab_querysets(viewer, tab)
    blocked = blocked_ids(viewer)
    # Suspended or banned members' things leave the feed with them.
    return (posts.exclude(author_id__in=blocked).exclude(id__in=hidden_post_ids(viewer))
            .filter(author__is_active=True),
            acts.exclude(user_id__in=blocked).exclude(id__in=hidden_activity_ids(viewer))
            .filter(user__is_active=True))


def _tab_querysets(viewer, tab):

    if tab == 'club':
        my_clubs = list(ClubMembership.objects.filter(user=viewer).values_list('club_id', flat=True))
        mates = ClubMembership.objects.filter(club_id__in=my_clubs).values('user_id')
        posts = Post.objects.filter(audience='club', club_id__in=my_clubs)
        acts = Activity.objects.filter(
            Q(visibility='club', club_id__in=my_clubs)
            | (Q(visibility='everyone') & Q(user_id__in=mates))
        )
        return posts, acts

    followee_ids = Follow.objects.filter(follower=viewer).values('followee_id')
    authors = Q(author=viewer) | Q(author_id__in=followee_ids)
    posts = Post.objects.filter(authors, audience='followers')
    acts = Activity.objects.filter(
        (Q(user=viewer) | Q(user_id__in=followee_ids)) & Q(visibility__in=['everyone', 'followers'])
    )
    return posts, acts


def page(viewer, tab, before=None, request=None, limit=PAGE):
    posts, acts = tab_querysets(viewer, tab)
    if before:
        posts = posts.filter(created_at__lt=before)
        acts = acts.filter(start_time__lt=before)
    posts = list(_annotate_posts(posts, viewer).order_by('-created_at')[:limit + 1])
    acts = list(_annotate_acts(acts, viewer).order_by('-start_time')[:limit + 1])
    items = [post_item(p, viewer, request) for p in posts] + [activity_item(a, viewer, request) for a in acts]
    items.sort(key=lambda i: i['sort'], reverse=True)
    more = len(items) > limit
    items = items[:limit]
    return {
        'items': items,
        'next': items[-1]['sort'] if more and items else None,
    }


def parse_before(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if timezone.is_aware(dt) else timezone.make_aware(dt)
