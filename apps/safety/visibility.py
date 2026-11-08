"""
Who a member shouldn't see. One place, used by every list and detail view.

- blocked_ids: blocks in either direction. Never shown, never reachable.
- not_interested_ids: people hidden from suggestions (Fit Buddies, Home).
- hidden_post_ids / hidden_activity_ids: items hidden from the feed,
  including ones hidden while a report is reviewed.
"""

from .models import Block


def blocked_ids(user):
    if not user or not user.is_authenticated:
        return set()
    cache = getattr(user, '_agf_blocked', None)
    if cache is None:
        cache = Block.between_ids(user)
        user._agf_blocked = cache  # per request: the user object lives for one request
    return cache


def is_blocked(user, other_id):
    return other_id in blocked_ids(user)


def _hides(user, kind, field):
    from apps.social.models import Hide
    return set(Hide.objects.filter(member=user, kind=kind).values_list(field, flat=True))


def not_interested_ids(user):
    return _hides(user, 'not_interested', 'target_user_id')


def hidden_post_ids(user):
    return _hides(user, 'hidden_post', 'target_post_id')


def hidden_activity_ids(user):
    return _hides(user, 'hidden_activity', 'target_activity_id')


def forget(user):
    """After a block or unblock in this request."""
    if hasattr(user, '_agf_blocked'):
        del user._agf_blocked
