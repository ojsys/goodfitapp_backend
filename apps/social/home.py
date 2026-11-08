"""
Everything on Home besides the feed: header counts, This Week, the
getting-started checklist and the new-member suggestions (Core-FeedNew).
"""

from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.activities.models import Activity
from apps.events.models import Event, EventRSVP
from apps.safety.visibility import blocked_ids, not_interested_ids
from apps.users.age_gate import safe_zone

from .feed import person
from .models import Club, ClubMembership, Follow, Post, Wave

INTEREST_LABELS = {
    'running': 'Running', 'cycling': 'Cycling', 'strength': 'Strength', 'yoga': 'Yoga',
    'hiking': 'Hiking', 'pilates': 'Pilates', 'hiit': 'HIIT', 'crossfit': 'CrossFit',
}
# Which interest an activity kind counts toward, and how it reads ("Rides 3x a week").
KIND_VERB = {'ride': 'Rides', 'run': 'Runs', 'walk': 'Walks', 'hike': 'Hikes', 'yoga': 'Does yoga',
             'strength': 'Lifts', 'pilates': 'Does pilates', 'hiit': 'Does HIIT', 'crossfit': 'Does CrossFit'}

# First-day Home is shown for this long after joining, until the checklist is
# finished and dismissed. (The spec says "first-day Home"; a week gives
# members who join midweek a chance to meet a weekend ride.)
NEW_MEMBER_DAYS = 7


def join_list(words):
    words = [w for w in words if w]
    if len(words) <= 1:
        return ''.join(words)
    return ', '.join(words[:-1]) + ' and ' + words[-1]


# ------------------------------------------------------------------ header

def header_counts(user):
    from apps.chats.services import total_unread
    # Notifications arrive in Phase 6.
    return {'messages': total_unread(user), 'notifications': 0}


# --------------------------------------------------------------- this week

def week(user, now=None):
    """Monday to Sunday in the member's time zone."""
    tz = safe_zone(user.timezone)
    now = (now or timezone.now()).astimezone(tz)
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    acts = Activity.objects.filter(user=user, start_time__gte=monday, start_time__lt=monday + timedelta(days=7))
    days = [0.0] * 7
    count, climb = 0, 0.0
    for a in acts:
        d = a.start_time.astimezone(tz).weekday()
        days[d] += a.distance or 0
        count += 1
        climb += a.elevation_gain or 0
    return {
        'distance': sum(days),
        'activities': count,
        'climb': climb,
        'days': days,
        'today': now.weekday(),
    }


# ---------------------------------------------------------------- checklist

def checklist(user, now=None):
    now = now or timezone.now()
    steps = {
        'account': True,
        'guidelines': bool(user.guidelines_agreed_at),
        'club': ClubMembership.objects.filter(user=user).exists(),
        'rsvp': EventRSVP.objects.filter(user=user, status='going').exists(),
        'intro': Post.objects.filter(author=user, is_intro=True).exists(),
        'activity': Activity.objects.filter(user=user).exists(),
    }
    done = sum(steps.values())
    all_done = done == len(steps)
    joined = user.created_at or now
    new_member = (now - joined) < timedelta(days=NEW_MEMBER_DAYS) and not (all_done and user.checklist_hidden)
    return {
        'steps': steps,
        'done': done,
        'total': len(steps),
        'hidden': user.checklist_hidden,
        'new_member_home': new_member,
    }


# -------------------------------------------------------------- suggestions

def club_card(club, user):
    return {
        'id': club.id,
        'name': club.name,
        'initials': club.initials,
        'color': club.color,
        'neighborhood': club.neighborhood,
        'tagline': club.tagline,
        'members': getattr(club, 'n_members', None) or club.memberships.count(),
        'joined': ClubMembership.objects.filter(club=club, user=user).exists(),
    }


def suggested_clubs(user, limit=3):
    interests = user.interests or []
    clubs = Club.objects.annotate(n_members=Count('memberships'))
    matching = [c for c in clubs if set(c.interests or []) & set(interests)]
    others = [c for c in clubs if c not in matching]
    ordered = sorted(matching, key=lambda c: -c.n_members) + sorted(others, key=lambda c: -c.n_members)
    based_on = [INTEREST_LABELS[i] for i in interests if i in INTEREST_LABELS]
    return {
        'based_on': join_list(based_on[:2]),
        'clubs': [club_card(c, user) for c in ordered[:limit]],
    }


def event_card(event, user, request=None):
    going = list(event.rsvps.filter(status='going').select_related('user').order_by('created_at'))
    blocked = blocked_ids(user)
    shown = [r for r in going if r.user_id not in blocked]
    tz = safe_zone(user.timezone)
    start = event.start_time.astimezone(tz)
    return {
        'id': event.id,
        'title': event.title,
        'start': event.start_time.isoformat(),
        'weekday': start.strftime('%a').upper(),
        'day': start.day,
        'month': start.strftime('%b'),
        'time': start.strftime('%-I:%M %p'),
        'location': event.location_name,
        'route_name': event.route_name,
        'distance': event.distance_m,
        'pace': event.pace,
        'no_drop': event.no_drop,
        'beginner_friendly': event.beginner_friendly,
        'tags': event.tags or [],
        'leader': person(event.leader, request)['first_name'] if event.leader else None,
        'going': len(going),
        'going_people': [person(r.user, request) for r in shown[:4]],
        'i_going': any(r.user_id == user.id for r in going),
        'club_id': event.club_id,
    }


def _upcoming():
    return Event.objects.filter(is_active=True, is_cancelled=False, start_time__gte=timezone.now())


def upcoming_group_ride(user, request=None):
    """The next ride you RSVP'd to, else the next one from your clubs."""
    mine = _upcoming().filter(rsvps__user=user, rsvps__status='going').order_by('start_time').first()
    if not mine:
        clubs = ClubMembership.objects.filter(user=user).values('club_id')
        mine = _upcoming().filter(club_id__in=clubs).order_by('start_time').first()
    return event_card(mine, user, request) if mine else None


def first_ride(user, request=None):
    beginner = _upcoming().filter(beginner_friendly=True).order_by('start_time').first()
    later = _upcoming().filter(beginner_friendly=False).order_by('start_time').first()
    return {
        'event': event_card(beginner, user, request) if beginner else None,
        'next': event_card(later, user, request) if later else None,
    }


def suggested_people(user, request=None, limit=2):
    """People Who Move Like You: members who share an interest."""
    from apps.users.models import User
    interests = set(user.interests or [])
    following = Follow.objects.filter(follower=user).values('followee_id')
    candidates = (
        User.objects.filter(is_active=True, guidelines_agreed_at__isnull=False)
        .exclude(id=user.id).exclude(id__in=following)
        .exclude(id__in=blocked_ids(user) | not_interested_ids(user))
        .order_by('-created_at')[:200]
    )
    scored = []
    for c in candidates:
        shared = interests & set(c.interests or [])
        if shared:
            scored.append((len(shared), c))
    scored.sort(key=lambda t: -t[0])
    since = timezone.now() - timedelta(days=28)
    waved = set(Wave.objects.filter(sender=user).values_list('recipient_id', flat=True))
    out = []
    for _, c in scored[:limit]:
        top = (Activity.objects.filter(user=c, start_time__gte=since)
               .values('type').annotate(n=Count('id')).order_by('-n').first())
        if top and top['n'] >= 4:
            line = f"{KIND_VERB.get(top['type'], 'Moves')} {round(top['n'] / 4)}x a week"
        else:
            line = 'Into ' + join_list([INTEREST_LABELS[i] for i in (c.interests or []) if i in INTEREST_LABELS][:2])
        p = person(c, request)
        p['line'] = ' · '.join(x for x in [line, c.neighborhood] if x)
        p['waved'] = c.id in waved
        out.append(p)
    return out
