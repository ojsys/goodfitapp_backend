"""
Who can see what, and what they see of a track.

Requirements (Location): "Privacy zones trim the first and last stretch of any
track near saved places before anyone else can see it. Apply on the server,
not just the map view." The owner always gets the full track; everyone else
gets `public_track()`.
"""

from math import asin, cos, radians, sin, sqrt

from django.db.models import Q

# With "hide start and end" on (the default), this much of each end is cut
# even when the track doesn't touch a saved place.
END_TRIM_M = 200


def haversine_m(a, b):
    lat1, lng1, lat2, lng2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371000 * asin(sqrt(h))


def _in_zone(p, zones):
    return any(haversine_m(p, (z.latitude, z.longitude)) <= z.radius_m for z in zones)


def _trim_count(points, meters):
    """How many points from the front cover `meters`."""
    if meters <= 0:
        return 0
    covered = 0.0
    for i in range(1, len(points)):
        covered += haversine_m(points[i - 1], points[i])
        if covered >= meters:
            return i
    return len(points)


def visible_range(points, owner, zones=None):
    """(start, end) slice of a track other members may see; start == end
    when none of it is visible.

    Trims every leading and trailing point inside one of the owner's privacy
    zones, then, if the owner hides track ends, END_TRIM_M more from each end.
    """
    if zones is None:
        zones = list(owner.privacy_zones.all()) if getattr(owner, 'privacy_zones_on', True) else []
    i, j = 0, len(points)
    if zones:
        while i < j and _in_zone(points[i], zones):
            i += 1
        while j > i and _in_zone(points[j - 1], zones):
            j -= 1
    if getattr(owner, 'hide_track_ends', True) and j > i:
        i += _trim_count(points[i:j], END_TRIM_M)
        if j > i:
            j -= _trim_count(list(reversed(points[i:j])), END_TRIM_M)
    if j - i < 2:
        return 0, 0
    return i, j


def public_track(points, owner, zones=None):
    """The part of a track (list of (lat, lng, ...)) others may see."""
    i, j = visible_range(points, owner, zones)
    return list(points[i:j])


def sample(points, limit):
    """Evenly spaced subset, keeping both ends."""
    n = len(points)
    if n <= limit:
        return list(points)
    step = (n - 1) / (limit - 1)
    return [points[round(i * step)] for i in range(limit)]


def track_for(activity, viewer, limit=None):
    """[[lat, lng], ...] of the activity's track as `viewer` may see it."""
    pts = activity.track_points()
    if viewer is None or viewer.id != activity.user_id:
        pts = public_track(pts, activity.user)
    if limit:
        pts = sample(pts, limit)
    return [[round(p[0], 6), round(p[1], 6)] for p in pts]


# ---------------------------------------------------------------- visibility

def follows(viewer, author_id):
    from .models import Follow
    return Follow.objects.filter(follower=viewer, followee_id=author_id).exists()


def club_ids(user):
    from .models import ClubMembership
    return set(ClubMembership.objects.filter(user=user).values_list('club_id', flat=True))


def _blocked(viewer, owner_id):
    from apps.safety.visibility import is_blocked
    return is_blocked(viewer, owner_id)


def can_view_activity(viewer, activity):
    if viewer.id == activity.user_id:
        return True
    if _blocked(viewer, activity.user_id):
        return False
    v = activity.visibility
    if v == 'everyone':
        return True
    if v == 'followers':
        return follows(viewer, activity.user_id)
    if v == 'club':
        return activity.club_id is not None and activity.club_id in club_ids(viewer)
    return False


def can_view_post(viewer, post):
    if viewer.id == post.author_id:
        return True
    if _blocked(viewer, post.author_id):
        return False
    if post.audience == 'followers':
        return follows(viewer, post.author_id)
    if post.audience == 'club':
        return post.club_id is not None and post.club_id in club_ids(viewer)
    return False


def visible_activities_q(viewer):
    """Activities by others that `viewer` may see (anywhere, e.g. detail)."""
    from .models import Follow
    from apps.safety.visibility import blocked_ids
    followee_ids = Follow.objects.filter(follower=viewer).values('followee_id')
    return (
        Q(user=viewer)
        | Q(visibility='everyone')
        | (Q(visibility='followers') & Q(user_id__in=followee_ids))
        | (Q(visibility='club') & Q(club_id__in=list(club_ids(viewer))))
    ) & ~Q(user_id__in=blocked_ids(viewer))
