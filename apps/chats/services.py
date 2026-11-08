"""Chat rules: membership, slow mode, sending, and response shapes."""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.safety.models import Block
from apps.social.feed import person
from apps.social.models import ClubMembership
from apps.users.age_gate import safe_zone

from .models import (SLOW_LOCK, SLOW_MAX, SLOW_WINDOW, SPAM_PAUSE, SPAM_STRIKES, SPAM_WINDOW, Chat, ChatMember,
                     ChatMessage)


class SlowMode(Exception):
    def __init__(self, until, paused=False):
        super().__init__('slow mode')
        self.until = until
        self.paused = paused


class ChatClosed(Exception):
    pass


# ------------------------------------------------------------- membership

def ride_chat(event, create=True):
    chat = Chat.objects.filter(event=event).first()
    if chat is None and create:
        chat, _ = Chat.objects.get_or_create(event=event, defaults={
            'kind': 'ride', 'closes_at': Chat.ride_close_time(event)})
    return chat


def join_ride_chat(event, user):
    chat = ride_chat(event)
    # Keep the close time in step if the event moved.
    close = Chat.ride_close_time(event)
    if chat.closes_at != close:
        Chat.objects.filter(pk=chat.pk).update(closes_at=close)
    ChatMember.objects.get_or_create(chat=chat, user=user)
    return chat


def leave_ride_chat(event, user):
    chat = ride_chat(event, create=False)
    if chat:
        ChatMember.objects.filter(chat=chat, user=user).delete()


def direct_chat(a, b):
    lo, hi = sorted([a.id, b.id])
    chat, _ = Chat.objects.get_or_create(pair_key=f'{lo}:{hi}', defaults={'kind': 'direct'})
    for u in (a, b):
        ChatMember.objects.get_or_create(chat=chat, user=u)
    return chat


def member(chat, user):
    return ChatMember.objects.filter(chat=chat, user=user).first()


# ------------------------------------------------------------------ roles

ROLE_BADGES = {'owner': 'Owner', 'admin': 'Admin', 'organizer': 'Organizer', 'ride_leader': 'Ride leader'}


def role_badges(chat):
    """user_id -> badge for ride chats: club team role, and the ride's leader."""
    ev = chat.event
    if not ev:
        return {}
    out = {}
    if ev.club_id:
        for m in ClubMembership.objects.filter(club_id=ev.club_id, role__in=ROLE_BADGES):
            out[m.user_id] = ROLE_BADGES[m.role]
    if ev.leader_id and ev.leader_id not in out:
        out[ev.leader_id] = 'Ride leader'
    if ev.kind == 'community' and ev.host_id not in out:
        out[ev.host_id] = 'Host'
    return out


def can_moderate(chat, user):
    ev = chat.event
    if not ev or not ev.club_id:
        return False
    m = ClubMembership.objects.filter(club_id=ev.club_id, user=user).first()
    return bool(m and m.can('moderate'))


# ---------------------------------------------------------------- sending

def check_slow_mode(m, now=None):
    """Raise SlowMode if the sender is locked, or this send trips the limit."""
    now = now or timezone.now()
    if m.locked_until and now < m.locked_until:
        raise SlowMode(m.locked_until, paused=(m.locked_until - now) > SLOW_LOCK)
    recent = ChatMessage.objects.filter(chat=m.chat, sender=m.user, created_at__gte=now - SLOW_WINDOW).count()
    if recent >= SLOW_MAX:
        if not m.strike_window_start or now - m.strike_window_start > SPAM_WINDOW:
            m.strike_window_start, m.strikes = now, 0
        m.strikes += 1
        paused = m.strikes >= SPAM_STRIKES
        m.locked_until = now + (SPAM_PAUSE if paused else SLOW_LOCK)
        m.save(update_fields=['locked_until', 'strikes', 'strike_window_start'])
        raise SlowMode(m.locked_until, paused=paused)


def send(chat, user, body='', attachment='', route=None, photo=None, lat=None, lng=None, live_minutes=None,
         client_id=''):
    if chat.is_closed:
        raise ChatClosed()
    m = member(chat, user)
    if m is None:
        raise PermissionError('Not in this chat')
    if client_id:
        dup = ChatMessage.objects.filter(sender=user, client_id=client_id).first()
        if dup:
            return dup
    check_slow_mode(m)
    live_until = timezone.now() + timedelta(minutes=live_minutes) if live_minutes else None
    try:
        with transaction.atomic():
            msg = ChatMessage.objects.create(chat=chat, sender=user, body=body, attachment=attachment, route=route,
                                             photo=photo, latitude=lat, longitude=lng, live_until=live_until,
                                             client_id=client_id or '')
    except IntegrityError:
        return ChatMessage.objects.get(sender=user, client_id=client_id)
    Chat.objects.filter(pk=chat.pk).update(last_message_at=msg.created_at)
    ChatMember.objects.filter(pk=m.pk).update(last_read_id=msg.id)
    return msg


# ----------------------------------------------------------------- shapes

def message_item(msg, viewer, badges, request=None):
    removed = msg.removed_at is not None
    item = {
        'id': msg.id,
        'client_id': msg.client_id or None,
        'sender': person(msg.sender, request) if msg.sender else None,
        'badge': badges.get(msg.sender_id) if msg.sender_id else None,
        'is_mine': msg.sender_id == viewer.id,
        'body': '' if removed else msg.body,
        'removed': removed,
        'attachment': '' if removed else msg.attachment,
        'created_at': msg.created_at.isoformat(),
    }
    if removed:
        return item
    if msg.attachment == 'route' and msg.route_id:
        from apps.routes.views import route_card
        r = route_card(msg.route, viewer, request, line_points=80)
        item['route'] = {k: r[k] for k in ('id', 'name', 'distance', 'elevation_gain', 'line', 'club_favorite',
                                           'is_loop', 'best_for')}
    if msg.attachment == 'photo' and msg.photo:
        item['photo'] = request.build_absolute_uri(msg.photo.url) if request else msg.photo.url
    if msg.attachment == 'location':
        live = bool(msg.live_until and timezone.now() < msg.live_until)
        item['location'] = {'latitude': msg.latitude, 'longitude': msg.longitude, 'live': live,
                            'live_until': msg.live_until.isoformat() if msg.live_until else None,
                            'updated_at': msg.updated_at.isoformat()}
    return item


def unread_count(chat, user, m=None):
    m = m or member(chat, user)
    if not m:
        return 0
    return chat.messages.filter(id__gt=m.last_read_id, removed_at=None).exclude(sender=user).count()


def other_in_direct(chat, user):
    return next((cm.user for cm in chat.members.select_related('user') if cm.user_id != user.id), None)


def chat_title(chat, user, request=None):
    if chat.kind == 'ride':
        return chat.event.title
    other = other_in_direct(chat, user)
    return person(other, request)['first_name'] if other else 'Chat'


def inbox_row(chat, user, request=None):
    last = chat.messages.filter(removed_at=None).select_related('sender').order_by('-id').first()
    preview = ''
    if chat.kind == 'ride' and chat.is_closed:
        preview = 'This chat closed 48 hours after the event.'
    elif last:
        what = last.body or {'route': 'Shared a route', 'photo': 'Sent a photo',
                             'location': 'Shared a location'}.get(last.attachment, '')
        who = 'You' if last.sender_id == user.id else (person(last.sender, request)['first_name'] if last.sender else '')
        preview = f'{who}: {what}' if chat.kind == 'ride' else (f'You: {what}' if last.sender_id == user.id else what)
    row = {
        'id': chat.id,
        'kind': chat.kind,
        'title': chat_title(chat, user, request),
        'preview': preview,
        'at': (last.created_at if last else chat.created_at).isoformat(),
        'unread': 0 if chat.is_closed else unread_count(chat, user),
        'closed': chat.is_closed,
    }
    if chat.kind == 'ride':
        row['activity_type'] = chat.event.activity_type
        row['soon'] = chat.event.start_time - timezone.now() < timedelta(days=2)
    else:
        other = other_in_direct(chat, user)
        row['person'] = person(other, request) if other else None
    return row


def chat_header(chat, user, request=None):
    from apps.social.home import event_card
    m = member(chat, user)
    head = {
        'id': chat.id,
        'kind': chat.kind,
        'title': chat_title(chat, user, request),
        'closed': chat.is_closed,
        'closes_at': chat.closes_at.isoformat() if chat.closes_at else None,
        'locked_until': m.locked_until.isoformat() if m and m.locked_until and m.locked_until > timezone.now() else None,
        'can_moderate': can_moderate(chat, user),
    }
    if chat.kind == 'ride':
        ev = chat.event
        card = event_card(ev, user, request)
        tz = safe_zone(user.timezone)
        head.update({
            'event': card,
            'subtitle': ' · '.join(x for x in [f"{card['going']} going", ev.club.name if ev.club_id else ''] if x),
            'people': card['going_people'][:3],
            'latitude': ev.latitude,
            'longitude': ev.longitude,
            'location': ev.location_name,
            'when': f"{card['time']} · {ev.location_name}" if ev.location_name else card['time'],
            'my_activity': _my_activity_for(ev, user, tz),
        })
    else:
        other = other_in_direct(chat, user)
        head.update({'person': person(other, request) if other else None,
                     'subtitle': other.neighborhood if other else ''})
    return head


def _my_activity_for(event, user, tz):
    """'See the ride' after a closed ride chat: your activity that day."""
    from apps.activities.models import Activity
    day = event.start_time.astimezone(tz).date()
    a = (Activity.objects.filter(user=user, start_time__date=day).order_by('start_time').first())
    return a.id if a else None


def visible_messages(chat, user):
    blocked = Block.between_ids(user)
    return chat.messages.exclude(sender_id__in=blocked).select_related('sender', 'route')


def chats_for(user):
    blocked = Block.between_ids(user)
    qs = (Chat.objects.filter(members__user=user)
          .select_related('event', 'event__club').prefetch_related('members__user').distinct())
    out = []
    for c in qs:
        if c.kind == 'direct':
            other = other_in_direct(c, user)
            if other is None or other.id in blocked:
                continue
            if not c.last_message_at:
                continue
        # Closed ride chats stay in the inbox for two weeks.
        if c.kind == 'ride' and c.closes_at and c.closes_at < timezone.now() - timedelta(days=14):
            continue
        out.append(c)
    return out


def total_unread(user):
    return sum(inbox_row(c, user)['unread'] for c in chats_for(user))


def direct_allowed(a, b):
    return b.id not in Block.between_ids(a) and b.is_active

