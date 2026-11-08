"""Create notifications. Everything goes through notify()."""

from django.utils import timezone

from . import push
from .models import Notification, NotificationSettings


def B(text):
    """Bold part."""
    return [str(text), True]


def T(text):
    return [str(text), False]


def _name(u):
    return (u.first_name or (u.display_name or '').split(' ')[0] or 'Someone') if u else 'Someone'


def _allowed(recipient, kind, actor):
    if not recipient or not recipient.is_active:
        return False
    if actor is not None:
        if actor.id == recipient.id:
            return False
        from apps.safety.visibility import is_blocked
        if is_blocked(recipient, actor.id):
            return False
    return NotificationSettings.of(recipient).allows(Notification.CATEGORY.get(kind, 'props_comments'))


def notify(recipient, kind, parts, actor=None, link='', group_key='', push_title=None):
    """Add a notification (and push it). Returns it, or None if the member
    turned this kind off, blocked the actor, or it's about themselves."""
    if not _allowed(recipient, kind, actor):
        return None
    n = Notification.objects.create(recipient=recipient, kind=kind, actor=actor, parts=parts, link=link,
                                    group_key=group_key, actor_ids=[actor.id] if actor else [])
    push.send(recipient, push_title or 'A Good Fit', n.text, {'link': link, 'id': n.id})
    return n


def notify_grouped_props(recipient, actor, target_label, link, group_key):
    """'Alex, Sasha and 12 others gave props to your Wednesday evening ride.'
    One unread row per thing; each new prop moves it to the top."""
    if not _allowed(recipient, 'props', actor):
        return None
    n = Notification.objects.filter(recipient=recipient, group_key=group_key, read_at__isnull=True).first()
    if n is None:
        return notify(recipient, 'props', [B(_name(actor)), T(' gave props to your '), B(target_label), T('.')],
                      actor=actor, link=link, group_key=group_key)
    if actor.id in n.actor_ids:
        return n
    from apps.users.models import User
    ids = [actor.id] + n.actor_ids
    names = {u.id: _name(u) for u in User.objects.filter(id__in=ids[:2])}
    count = n.count + 1
    if count == 2:
        who = f'{names[ids[0]]} and {names[ids[1]]}'
    else:
        others = count - 2
        who = f'{names[ids[0]]}, {names[ids[1]]} and {others} other{"s" if others != 1 else ""}'
    n.parts = [B(who), T(' gave props to your '), B(target_label), T('.')]
    n.actor_ids, n.count, n.actor = ids[:20], count, actor
    n.updated_at = timezone.now()
    n.save()
    return n


def push_only(recipient, kind, title, body, link=''):
    """Pushes that don't add a row (chat messages: they have their own inbox)."""
    if recipient and recipient.is_active and NotificationSettings.of(recipient).allows(
            Notification.CATEGORY.get(kind, 'messages') if kind != 'message' else 'messages'):
        push.send(recipient, title, body, {'link': link})


def unread_count(user):
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()
