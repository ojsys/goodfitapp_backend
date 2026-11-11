"""
Community (Phase 3): the hub, club pages, events browse, hosting and
Fit Buddies. Data shaping lives here; HTTP in community_views.py.
"""

from apps.business.services import featured_for, pending_invite
from collections import Counter
from datetime import datetime, time, timedelta

from django.db.models import Q, Sum
from django.utils import timezone

from apps.activities.models import Activity
from apps.events.models import Event, EventRSVP
from apps.safety.visibility import blocked_ids, not_interested_ids
from apps.users.age_gate import safe_zone

from .feed import person
from .home import INTEREST_LABELS, event_card
from .models import (Announcement, Club, ClubGoal, ClubMembership, Follow, RideInvite)
from .privacy import haversine_m

MI = 1609.344


def local_now(user):
    return timezone.now().astimezone(safe_zone(user.timezone))


def week_start(user):
    now = local_now(user)
    return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def miles_between(a, b):
    if not (a.approx_lat and a.approx_lng and b.approx_lat and b.approx_lng):
        return None
    return haversine_m((a.approx_lat, a.approx_lng), (b.approx_lat, b.approx_lng)) / MI


# ------------------------------------------------------------------ clubs

def member_ids(club):
    return ClubMembership.objects.filter(club=club).values('user_id')


def shared_activities(qs):
    """Activities that count toward club totals: not Only me."""
    return qs.exclude(visibility='me')


def current_goal(club, user=None):
    now = timezone.now()
    g = ClubGoal.objects.filter(club=club, starts_at__lte=now, ends_at__gt=now).first()
    if not g:
        return None
    acts = shared_activities(Activity.objects.filter(user_id__in=member_ids(club), start_time__gte=g.starts_at,
                                                     start_time__lt=g.ends_at, distance__gt=0))
    if g.kinds:
        acts = acts.filter(type__in=g.kinds)
    total = acts.aggregate(d=Sum('distance'))['d'] or 0
    contributors = acts.values('user_id').distinct().count()
    mine = acts.filter(user=user).aggregate(d=Sum('distance'))['d'] or 0 if user else 0
    tz = safe_zone(user.timezone) if user else timezone.get_current_timezone()
    days_left = max(0, (g.ends_at.astimezone(tz).date() - timezone.now().astimezone(tz).date()).days)
    return {
        'title': g.title,
        'label': f"{g.starts_at.astimezone(tz).strftime('%B')} Club Goal",
        'progress': total,
        'target': g.target_m,
        'pct': min(100, round(total / g.target_m * 100)) if g.target_m else 0,
        'days_left': days_left,
        'mine': mine,
        'contributors': contributors,
    }


def club_summary(club, user, request=None):
    m = ClubMembership.objects.filter(club=club, user=user).first()
    goal = current_goal(club, user)
    return {
        'id': club.id,
        'name': club.name,
        'initials': club.initials,
        'color': club.color,
        'tagline': club.tagline,
        'members': club.memberships.count(),
        'role': (m.title or m.role_label) if m else None,
        'is_team': bool(m and m.role != 'member'),
        'goal_pct': goal['pct'] if goal else None,
    }


def leaders(club, user, request=None, since=None, limit=50):
    since = since or week_start(user)
    rows = (shared_activities(Activity.objects.filter(user_id__in=member_ids(club), start_time__gte=since,
                                                      distance__gt=0, user__is_active=True)
                                .exclude(user_id__in=blocked_ids(user)))
            .values('user_id').annotate(d=Sum('distance')).order_by('-d')[:limit])
    from apps.users.models import User
    users = {u.id: u for u in User.objects.filter(id__in=[r['user_id'] for r in rows])}
    return [{'rank': i + 1, 'person': person(users[r['user_id']], request), 'distance': r['d'],
             'is_me': r['user_id'] == user.id} for i, r in enumerate(rows)]


def club_page(club, user, request=None):
    tz = safe_zone(user.timezone)
    mine = ClubMembership.objects.filter(club=club, user=user).first()
    members = club.memberships.count()
    ws = week_start(user)
    acts = shared_activities(Activity.objects.filter(user_id__in=member_ids(club)))
    pinned = Announcement.objects.filter(club=club, pinned=True).select_related('author').first()
    board = leaders(club, user, request, since=ws)
    top = board[:4]
    me_row = next((r for r in board if r['is_me']), None)
    if me_row and me_row not in top:
        top = board[:3] + [me_row]
    blocked = blocked_ids(user)
    team = (ClubMembership.objects.filter(club=club, role__in=ClubMembership.TEAM_ROLES).select_related('user')
            .exclude(user_id__in=blocked).order_by('joined_at'))
    order = {r: i for i, r in enumerate(ClubMembership.TEAM_ROLES)}
    team = sorted(team, key=lambda t: order[t.role])
    preview = (ClubMembership.objects.filter(club=club).exclude(user_id__in=blocked).select_related('user')
               .order_by('-joined_at')[:6])
    upcoming = (Event.objects.filter(club=club, is_active=True, is_cancelled=False, start_time__gte=timezone.now())
                .order_by('start_time'))
    banner = club.banner.url if club.banner else None
    return {
        'id': club.id,
        'name': club.name,
        'initials': club.initials,
        'color': club.color,
        'banner': request.build_absolute_uri(banner) if banner and request else banner,
        'meta': ' · '.join(x for x in [club.location or club.neighborhood, f'{members:,} member{"" if members == 1 else "s"}',
                                        f'Founded {club.founded_year}' if club.founded_year else ''] if x),
        'members': members,
        'joined': bool(mine),
        'role': mine.role if mine else None,
        'can_leave': bool(mine and mine.role != 'owner'),
        'goal': current_goal(club, user),
        'pinned': {'author': person(pinned.author, request)['name'] if pinned.author else club.name,
                   'text': pinned.text} if pinned else None,
        'stats': {
            'all_time': acts.aggregate(d=Sum('distance'))['d'] or 0,
            'this_week': acts.filter(start_time__gte=ws).aggregate(d=Sum('distance'))['d'] or 0,
            'activities_this_week': acts.filter(start_time__gte=ws).count(),
            'label': {'cycling': 'Rides This Week', 'running': 'Runs This Week'}.get(
                (club.interests or [''])[0], 'Workouts This Week'),
        },
        'leaders': top,
        'week_label': f"{ws.strftime('%b %-d')} – {(ws + timedelta(days=6)).strftime('%b %-d')}",
        'upcoming': [event_card(e, user, request) for e in upcoming[:10]],
        'recent': [recent_ride(e, user) for e in
                   Event.objects.filter(club=club, start_time__lt=timezone.now(),
                                        start_time__gte=timezone.now() - timedelta(days=60))
                   .order_by('-start_time')[:5]],
        'team': [{'person': person(t.user, request),
                  'label': ' · '.join(x for x in [t.title, t.role_label] if x)} for t in team],
        'member_preview': [person(m.user, request) for m in preview],
        'tz': str(tz),
        # An invite to the club team from the business portal.
        'team_invite': pending_invite(user, club),
    }


def recent_ride(e, user):
    tz = safe_zone(user.timezone)
    riders = e.rsvps.filter(status='going').count()
    bits = [e.start_time.astimezone(tz).strftime('%b %-d'), e.location_name, f'{riders} rider{"" if riders == 1 else "s"}']
    if e.distance_m:
        bits.append(f'{e.distance_m / MI:.1f} mi' if user.units != 'km' else f'{e.distance_m / 1000:.1f} km')
    return {'id': e.id, 'title': e.title, 'meta': ' · '.join(b for b in bits if b)}


def club_members(club, user, request=None, offset=0, limit=50):
    qs = (ClubMembership.objects.filter(club=club).exclude(user_id__in=blocked_ids(user)).select_related('user')
          .order_by('-role', 'user__first_name')[offset:offset + limit])
    order = {r: i for i, r in enumerate(('owner', 'admin', 'organizer', 'ride_leader', 'member'))}
    rows = sorted(qs, key=lambda m: order[m.role])
    return [{'person': person(m.user, request), 'is_me': m.user_id == user.id,
             'line': ' · '.join(x for x in [m.role_label if m.role != 'member' else 'Member',
                                            m.user.neighborhood] if x)} for m in rows]


# ------------------------------------------------------------------ hub

def weekend_events(user, request=None):
    now = local_now(user)
    # Saturday and Sunday of this week (or today, if it's the weekend).
    sat = (now + timedelta(days=(5 - now.weekday()) % 7)).date() if now.weekday() < 5 else \
        now.date() - timedelta(days=now.weekday() - 5)
    start = datetime.combine(sat, time.min, tzinfo=now.tzinfo)
    end = start + timedelta(days=2)
    start = max(start, timezone.now())
    return [e for e in visible_events(user).filter(start_time__gte=start, start_time__lt=end)
            .order_by('start_time')[:3]]


def hub(user, request=None):
    from apps.chats import services as chat_svc
    clubs = [club_summary(m.club, user, request)
             for m in ClubMembership.objects.filter(user=user).select_related('club').order_by('joined_at')]
    rows = [chat_svc.inbox_row(c, user, request) for c in chat_svc.chats_for(user)]
    # Match chats stay inside A Good Match.
    rows = sorted([r for r in rows if not r['closed'] and r['kind'] != 'match'], key=lambda r: r['at'],
                  reverse=True)[:2]
    messages = []
    for r in rows:
        if r['kind'] == 'ride':
            ev_chat = chat_svc.Chat.objects.select_related('event').get(pk=r['id'])
            people = [person(cm.user, request) for cm in ev_chat.members.select_related('user')[:2]]
        else:
            people = [r['person']] if r.get('person') else []
        messages.append({'id': r['id'], 'title': r['title'], 'people': people, 'preview': r['preview'],
                         'at': r['at'], 'unread': r['unread']})
    buddies = buddy_suggestions(user, request, limit=20)
    return {
        'clubs': clubs,
        'weekend': [event_card(e, user, request) for e in weekend_events(user, request)],
        'messages': messages,
        'buddies': {'count': len(buddies), 'people': [b['person'] for b in buddies[:3]]},
        'match': user.match_opted_in,
        # Partner placements.
        'featured': featured_for(user, 'hub', request),
    }


# ------------------------------------------------------------------ events

def visible_events(user):
    my_clubs = ClubMembership.objects.filter(user=user).values('club_id')
    invited = RideInvite.objects.filter(recipient=user).values('event_id')
    return Event.objects.filter(is_active=True, is_cancelled=False).filter(
        Q(who_can_join='anyone') | Q(club_id__in=my_clubs) | Q(host=user) | Q(id__in=invited)
        | Q(rsvps__user=user)).distinct()


def browse_card(e, user, request=None):
    card = event_card(e, user, request)
    following = set(Follow.objects.filter(follower=user).values_list('followee_id', flat=True))
    blocked = blocked_ids(user)
    going = [r for r in e.rsvps.filter(status='going').select_related('user').order_by('created_at')
             if r.user_id not in blocked]
    friends = [r.user for r in going if r.user_id in following]
    if friends:
        first = person(friends[0], request)['first_name']
        friends_line = (f'{first} is going' if len(friends) == 1 else
                        f'{first} and {len(friends) - 1} other{"s" if len(friends) > 2 else ""} you follow')
    else:
        friends_line = ''
    people = friends[:3] + [r.user for r in going if r.user_id not in following][:max(0, 3 - len(friends))]
    card.update({
        'kind': e.kind,
        'kind_label': 'Club' if e.kind == 'club' else ('Featured' if e.kind == 'featured' else 'Community'),
        'host': e.club.name if e.club_id else (e.host_label or person(e.host, request)['name']),
        'activity_type': e.activity_type,
        'level': e.level,
        'duration_min': e.duration_min,
        'friends_line': friends_line,
        'going_people': [person(u, request) for u in people],
        'latitude': e.latitude,
        'longitude': e.longitude,
        'line': (e.route.line[::max(1, len(e.route.line) // 120)] if e.route_id else []),
        'date': e.start_time.astimezone(safe_zone(user.timezone)).date().isoformat(),
        'is_host': e.host_id == user.id,
    })
    return card


def browse(user, day=None, kind=None, request=None):
    tz = safe_zone(user.timezone)
    today = local_now(user).date()
    days = [today + timedelta(days=i) for i in range(7)]
    window_start = datetime.combine(today, time.min, tzinfo=tz)
    window = visible_events(user).filter(start_time__gte=max(window_start, timezone.now() - timedelta(hours=3)),
                                         start_time__lt=window_start + timedelta(days=7))
    if kind:
        window = window.filter(activity_type=kind)
    by_day = Counter(e.start_time.astimezone(tz).date() for e in window)
    day = day or next((d for d in days if by_day[d]), today)
    start = datetime.combine(day, time.min, tzinfo=tz)
    items = window.filter(start_time__gte=start, start_time__lt=start + timedelta(days=1)).order_by('start_time')
    # The top slot on Events (every package).
    top = featured_for(user, 'events', request)
    if top:
        items = items.exclude(pk=top['id'])
    plans = (Event.objects.filter(rsvps__user=user, rsvps__status='going', is_cancelled=False,
                                  start_time__gte=timezone.now(), start_time__lt=window_start + timedelta(days=7))
             .order_by('start_time'))
    return {
        'days': [{'date': d.isoformat(), 'weekday': d.strftime('%a'), 'day': d.day, 'has_events': by_day[d] > 0,
                  'label': ('Today · ' if d == today else '') + d.strftime('%A, %b %-d')} for d in days],
        'date': day.isoformat(),
        'featured': top,
        'items': [browse_card(e, user, request) for e in items],
        'plans': [{'id': e.id, 'title': e.title, 'activity_type': e.activity_type,
                   'when': e.start_time.astimezone(tz).strftime('%a %-d · %-I:%M %p'),
                   'start': e.start_time.isoformat(),
                   'end': (e.end_time or e.start_time + timedelta(minutes=e.duration_min or 120)).isoformat(),
                   'location': e.location_name} for e in plans],
    }


def can_see_event(user, e):
    """visible_events for one event, cancelled ones included (a "ride
    cancelled" notification still opens the event)."""
    if not e.is_active:
        return False
    if e.who_can_join == 'anyone' or e.host_id == user.id:
        return True
    if e.club_id and ClubMembership.objects.filter(user=user, club_id=e.club_id).exists():
        return True
    return (RideInvite.objects.filter(recipient=user, event=e).exists()
            or e.rsvps.filter(user=user).exists())


def event_detail(e, user, request=None):
    """One event (the Details link on Home, chats, featured cards and Events)."""
    from apps.business.models import FeaturedPlacement
    from apps.chats.models import Chat
    tz = safe_zone(user.timezone)
    card = browse_card(e, user, request)
    blocked = blocked_ids(user)
    going = [r.user for r in e.rsvps.filter(status='going').select_related('user').order_by('created_at')
             if r.user_id not in blocked]
    start = e.start_time.astimezone(tz)
    end = e.end_time or (e.start_time + timedelta(minutes=e.duration_min or 120))
    chat = Chat.objects.filter(event=e).first()
    placement = (FeaturedPlacement.objects.filter(event=e, status='approved').select_related('account')
                 .order_by('-starts_at').first() if e.kind == 'featured' else None)
    route = e.route if e.route_id else None
    card.update({
        'description': e.description or '',
        'address': e.location_address if e.location_address != e.location_name else '',
        'when': f'{start:%A, %B} {start.day} · {start:%-I:%M %p}',
        'end': end.isoformat(),
        'cancelled': e.is_cancelled,
        'past': end < timezone.now(),
        'price_line': 'Free' if e.price_type == 'Free' else (f'${e.price_amount:.0f}' if e.price_amount else ''),
        'what_to_bring': e.what_to_bring or [],
        'who_can_join': e.who_can_join,
        'leader_person': person(e.leader, request) if e.leader_id and e.leader_id not in blocked else None,
        'club': {'id': e.club.id, 'name': e.club.name, 'initials': e.club.initials, 'color': e.club.color}
        if e.club_id else None,
        'route': {'id': route.id, 'name': route.name, 'distance': route.distance_m,
                  'elevation_gain': route.elevation_gain_m} if route else None,
        'attendees': [person(u, request) for u in going[:30]],
        # Members in the ride chat: only people who are going.
        'chat': chat.id if chat and card['i_going'] else None,
        'host_line': (f'Hosted by {placement.account.name}' + (' · Verified business' if placement.account.verified
                                                                else '')) if placement else '',
    })
    return card


PACE_LABELS = {'social': 'social pace', 'steady': 'steady pace', 'fast': 'fast pace'}
PACE_LEVEL = {'social': 'easy', 'steady': 'moderate', 'fast': 'hard'}


# ------------------------------------------------------------------ buddies

def _schedule(acts, tz):
    """Which of mornings / evenings / weekends a member usually moves in."""
    buckets = Counter()
    for a in acts:
        t = a.start_time.astimezone(tz)
        if t.weekday() >= 5:
            buckets['Weekends'] += 1
        if t.hour < 10:
            buckets['Early mornings'] += 1
        elif t.hour >= 17:
            buckets['Evenings'] += 1
    n = len(acts) or 1
    return [k for k, v in buckets.items() if v / n >= 0.4]


def _profile(u, tz, since):
    acts = list(Activity.objects.filter(user=u, start_time__gte=since))
    kinds = Counter(a.type for a in acts)
    main = kinds.most_common(1)[0][0] if kinds else None
    main_acts = [a for a in acts if a.type == main and a.moving_time and a.distance]
    speed = (sum(a.distance for a in main_acts) / sum(a.moving_time for a in main_acts)) if main_acts else None
    weekly = sum(a.distance or 0 for a in acts if a.type == main) / 4 if main else 0
    routes = set(a.route_ref_id for a in acts if a.route_ref_id)
    return {'main': main, 'speed': speed, 'weekly': weekly, 'schedule': _schedule(acts, tz), 'routes': routes}


KIND_INTEREST = {'ride': 'cycling', 'run': 'running', 'yoga': 'yoga'}
SCHEDULE_FILTER = {'mornings': 'Early mornings'}


def buddy_suggestions(user, request=None, flt=None, limit=10):
    from apps.users.models import User
    tz = safe_zone(user.timezone)
    since = timezone.now() - timedelta(days=28)
    hidden = not_interested_ids(user) | blocked_ids(user)
    candidates = (User.objects.filter(is_active=True, guidelines_agreed_at__isnull=False)
                  .exclude(id=user.id).exclude(id__in=hidden).order_by('-last_seen')[:300])
    me = _profile(user, tz, since)
    my_interests = set(user.interests or [])
    my_clubs = set(ClubMembership.objects.filter(user=user).values_list('club_id', flat=True))
    my_events = set(EventRSVP.objects.filter(user=user, status='going', event__start_time__gte=timezone.now())
                    .values_list('event_id', flat=True))
    waved = set(user.waves_sent.values_list('recipient_id', flat=True))
    invited = set(RideInvite.objects.filter(sender=user).values_list('recipient_id', flat=True))
    out = []
    for c in candidates:
        shared_interests = my_interests & set(c.interests or [])
        if not shared_interests:
            continue
        p = _profile(c, tz, since)
        dist = miles_between(user, c)
        if flt in KIND_INTEREST and KIND_INTEREST[flt] not in (c.interests or []):
            continue
        if flt in SCHEDULE_FILTER and SCHEDULE_FILTER[flt] not in p['schedule']:
            continue
        if flt == 'near' and (dist is None or dist > 3):
            continue
        same_pace = bool(me['speed'] and p['speed'] and me['main'] == p['main']
                         and abs(me['speed'] - p['speed']) / me['speed'] <= 0.15)
        shared_sched = [s for s in p['schedule'] if s in me['schedule']]
        shared_routes = len(me['routes'] & p['routes'])
        score = 2 * len(shared_interests) + (2 if same_pace else 0) + len(shared_sched) + shared_routes \
            + (2 if dist is not None and dist <= 3 else 0)
        chips = (['Same pace'] if same_pace else []) + shared_sched[:1] + \
            ([f'{shared_routes} shared route{"s" if shared_routes > 1 else ""}'] if shared_routes else [])
        new_to = (ClubMembership.objects.filter(user=c, club_id__in=my_clubs,
                                                joined_at__gte=timezone.now() - timedelta(days=7))
                  .select_related('club').first())
        both = (Event.objects.filter(id__in=my_events, rsvps__user=c, rsvps__status='going')
                .order_by('start_time').first())
        pr = person(c, request)
        labels = [INTEREST_LABELS[i] for i in (c.interests or []) if i in INTEREST_LABELS]
        out.append({
            'score': score,
            'person': pr,
            'verified': c.id_verified,
            'meta': ' · '.join(x for x in [c.neighborhood, f'{dist:.1f} mi away' if dist is not None else '',
                                           f'New to {new_to.club.name.split()[0]} this week' if new_to else ''] if x),
            'short_meta': ' · '.join(x for x in [c.neighborhood, f'{dist:.1f} mi' if dist is not None else ''] if x),
            'line': ' · '.join(labels[:2] + p['schedule'][:1]),
            'chips': chips,
            'main': p['main'],
            'weekly': p['weekly'],
            'speed': p['speed'],
            'club_rides': EventRSVP.objects.filter(user=c, status='going', event__club_id__in=my_clubs,
                                                   event__start_time__lt=timezone.now()).count(),
            'tags': labels[:2] + list(c.buddy_tags or [])[:2],
            'prompt': {'q': c.prompt_question, 'a': c.prompt_answer} if c.prompt_answer else None,
            'both_going': ({'id': both.id, 'title': both.title,
                            'day': both.start_time.astimezone(tz).strftime('%A'),
                            'time': both.start_time.astimezone(tz).strftime('%-I:%M %p')} if both else None),
            'waved': c.id in waved,
            'invited': c.id in invited,
        })
    out.sort(key=lambda b: -b['score'])
    return out[:limit]

