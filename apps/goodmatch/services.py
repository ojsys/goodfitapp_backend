"""A Good Match rules and payloads. HTTP lives in views.py."""

import datetime as dt
import logging
from collections import Counter

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.users.age_gate import safe_zone

from .models import MAX_PROMPTS, PROMPTS, Decision, Match, MatchProfile

log = logging.getLogger(__name__)

# Fresh profiles per day. The day turns over at 9:00 AM local, the same time
# a cooldown ends ("New matches arrive each morning").
DAILY = 5
DAY_TURNS_AT = 9
# A pass hides someone for this long, then they can come around again.
PASS_DAYS = 30
POOL = 400
IDEA_DAYS = 14
NEAR_MI = 2.0
MI = 1609.344

INTEREST_KINDS = {'cycling': ['ride'], 'running': ['run'], 'yoga': ['yoga'], 'hiking': ['hike'],
                  'walking': ['walk', 'hike'], 'pilates': ['pilates'], 'strength': ['strength'],
                  'hiit': ['hiit'], 'crossfit': ['crossfit'], 'swimming': ['swim']}


class NotAllowed(Exception):
    def __init__(self, code, message, http=400):
        super().__init__(message)
        self.code, self.message, self.http = code, message, http


# ------------------------------------------------------------------ basics

def opted_in(u):
    return bool(u and u.is_active and u.match_opted_in and u.is_member)


def local_now(user, now=None):
    return (now or timezone.now()).astimezone(safe_zone(user.timezone))


def day_start(user, now=None):
    """The last 9:00 AM (the member's time): today's batch started then."""
    t = local_now(user, now)
    start = t.replace(hour=DAY_TURNS_AT, minute=0, second=0, microsecond=0)
    return start if t >= start else start - dt.timedelta(days=1)


def tomorrow_nine(user, now=None):
    """Moving on: new matches arrive at 9:00 AM the next day."""
    t = local_now(user, now)
    return (t + dt.timedelta(days=1)).replace(hour=DAY_TURNS_AT, minute=0, second=0, microsecond=0)


def age_of(u):
    try:
        return u.age
    except Exception:  # an unreadable birthday never breaks the screen
        return None


def holding(user):
    """The match that keeps `user` from new ones, if any."""
    for m in Match.involving(user).filter(state__in=('locked', 'met')).select_related('a', 'b', 'chat'):
        if m.holds(user):
            return m
    return None


def available(u, profile=None):
    """Can `u` get a new match right now?"""
    if not opted_in(u) or u.match_paused:
        return False
    p = profile or MatchProfile.objects.filter(user=u).first()
    if p and p.cooling:
        return False
    return holding(u) is None


def miles(a, b):
    from apps.social.community import miles_between
    return miles_between(a, b)


def decided_today(user, now=None):
    return Decision.objects.filter(actor=user, created_at__gte=day_start(user, now)).count()


# ------------------------------------------------------------- candidates

def _fits(me, my_p, other, other_p, my_age, their_age, dist):
    if not my_p.wants(other_p.gender) or not other_p.wants(my_p.gender):
        return False
    if their_age is None or not (my_p.age_min <= their_age <= my_p.age_max):
        return False
    if my_age is not None and not (other_p.age_min <= my_age <= other_p.age_max):
        return False
    if dist is not None and (dist > my_p.max_miles or dist > other_p.max_miles):
        return False
    return True


def candidates(user, now=None):
    """Who `user` could see next, best first. Each is (user, profile, miles)."""
    from apps.safety.visibility import blocked_ids, not_interested_ids
    from apps.users.models import User
    now = now or timezone.now()
    me_p = MatchProfile.of(user)
    my_age = age_of(user)
    skip = blocked_ids(user) | not_interested_ids(user) | {user.id}
    skip |= set(Decision.objects.filter(actor=user).filter(
        action='like').values_list('target_id', flat=True))
    skip |= set(Decision.objects.filter(actor=user, action='pass', created_at__gte=now - dt.timedelta(days=PASS_DAYS))
                .values_list('target_id', flat=True))
    for a, b in Match.involving(user).values_list('a_id', 'b_id'):
        skip |= {a, b}
    pool = (User.objects.filter(is_active=True, guidelines_agreed_at__isnull=False, match_paused=False,
                                intents__contains=['romantic'])
            .exclude(id__in=skip).order_by('-last_seen')[:POOL])
    pool = [u for u in pool if opted_in(u)]
    ids = [u.id for u in pool]
    held = set()
    for a, b, a_open, b_open in Match.objects.filter(state__in=('locked', 'met')).filter(
            Q(a_id__in=ids) | Q(b_id__in=ids)).values_list('a_id', 'b_id', 'a_open', 'b_open'):
        held |= ({a} if not a_open else set()) | ({b} if not b_open else set())
    profiles = {p.user_id: p for p in MatchProfile.objects.filter(user_id__in=[u.id for u in pool])}
    liked_me = set(Decision.objects.filter(target=user, action='like').values_list('actor_id', flat=True))
    mine = set(user.interests or [])
    out = []
    for u in pool:
        p = profiles.get(u.id) or MatchProfile(user=u)
        if p.cooling or u.id in held:
            continue
        dist = miles(user, u)
        if not _fits(user, me_p, u, p, my_age, age_of(u), dist):
            continue
        score = 3 * len(mine & set(u.interests or [])) + (2 if u.id in liked_me else 0) \
            + (2 if dist is not None and dist <= 3 else 0) + (1 if p.prompts else 0)
        out.append((score, u, p, dist))
    out.sort(key=lambda x: -x[0])
    return [(u, p, d) for _, u, p, d in out]


# ---------------------------------------------------------------- the card

def _speed_label(kind, mps, units):
    if not mps:
        return ''
    if kind in ('run', 'walk', 'hike'):
        per = (MI if units == 'mi' else 1000) / mps
        return f'{int(per // 60)}:{int(per % 60):02d} /{"mi" if units == "mi" else "km"}'
    return f'{mps * 3600 / (MI if units == "mi" else 1000):.0f} {"mph" if units == "mi" else "km/h"}'


def habits(u, viewer, now=None):
    """'Rides 3x a week' and the pace, from the last four weeks."""
    from apps.activities.models import Activity
    from apps.social.community import _schedule
    from apps.social.home import KIND_VERB
    now = now or timezone.now()
    acts = list(Activity.objects.filter(user=u, start_time__gte=now - dt.timedelta(days=28)))
    kinds = Counter(a.type for a in acts)
    main = kinds.most_common(1)[0][0] if kinds else None
    usually = ''
    if main:
        per_week = round(kinds[main] / 4)
        verb = KIND_VERB.get(main, 'Moves')
        usually = f'{verb} {per_week}× a week' if per_week >= 1 else f'{verb} now and then'
    timed = [a for a in acts if a.type == main and a.moving_time and a.distance]
    mps = sum(a.distance for a in timed) / sum(a.moving_time for a in timed) if timed else None
    return {'main': main, 'usually': usually, 'speed': _speed_label(main, mps, viewer.units),
            'schedule': _schedule(acts, safe_zone(viewer.timezone))}


def first_date_idea(viewer, other, now=None):
    """An upcoming open event both would enjoy, near both of them. Never a
    featured (paid) event: those don't appear in A Good Match."""
    from apps.events.models import Event
    from apps.social.privacy import haversine_m
    now = now or timezone.now()
    shared = set(viewer.interests or []) & set(other.interests or [])
    kinds = {k for i in shared for k in INTEREST_KINDS.get(i, [])}
    qs = (Event.objects.filter(is_active=True, is_cancelled=False, who_can_join='anyone',
                               start_time__gt=now + dt.timedelta(hours=3),
                               start_time__lt=now + dt.timedelta(days=IDEA_DAYS))
          .exclude(kind='featured').select_related('club').order_by('start_time')[:60])
    events = list(qs)
    if not events:
        return None

    def far(e, u):
        if e.latitude is None or not u.approx_lat:
            return None
        return haversine_m((e.latitude, e.longitude), (u.approx_lat, u.approx_lng)) / MI

    def rank(e):
        d = [x for x in (far(e, viewer), far(e, other)) if x is not None]
        return (0 if e.activity_type in kinds else 1, max(d) if d else 99, e.start_time)

    e = sorted(events, key=rank)[0]
    return event_idea(e, viewer, other)


def event_idea(e, viewer, other=None):
    from apps.social.privacy import haversine_m
    tz = safe_zone(viewer.timezone)
    t = e.start_time.astimezone(tz)
    when = f'{t:%a, %b} {t.day} · {t:%-I:%M %p}'
    place = e.location_name or ''
    both_near = False
    if other is not None and e.latitude is not None and viewer.approx_lat and other.approx_lat:
        both_near = all(haversine_m((e.latitude, e.longitude), (u.approx_lat, u.approx_lng)) / MI <= NEAR_MI
                        for u in (viewer, other))
    return {'id': e.id, 'title': e.title, 'when': when, 'place': place,
            'line': ' · '.join(x for x in [when, f'You’re both near {place}' if both_near and place else place] if x),
            'short': ' · '.join(x for x in [when, place] if x)}


def card(viewer, u, p, dist, request=None):
    from apps.social.feed import person
    from apps.social.home import INTEREST_LABELS
    h_me, h = habits(viewer, viewer), habits(u, viewer)
    shared = [INTEREST_LABELS.get(i, i.title()) for i in (u.interests or []) if i in (viewer.interests or [])]
    shared += [s for s in h['schedule'] if s in h_me['schedule']]
    prompts = [x for x in (p.prompts or []) if x.get('q') and x.get('a')][:MAX_PROMPTS]
    pace = ' '.join(x for x in [p.pace_note, h['speed']] if x)
    stats = [x for x in [{'label': 'Usually', 'value': h['usually']} if h['usually'] else None,
                         {'label': 'Pace', 'value': pace} if pace else None] if x]
    return {
        'person': person(u, request),
        'age': age_of(u),
        'verified': u.id_verified,
        'meta': ' · '.join(x for x in [u.neighborhood, f'{dist:.1f} mi away' if dist is not None else ''] if x),
        'shared': shared[:4],
        'prompts': prompts,
        'stats': stats,
        'idea': first_date_idea(viewer, u),
    }


# --------------------------------------------------------------- the state

def _matched_label(m, viewer):
    days = (local_now(viewer).date() - local_now(viewer, m.locked_at).date()).days
    if days <= 0:
        return 'Matched today'
    if days == 1:
        return 'Matched yesterday'
    t = local_now(viewer, m.locked_at)
    return f'Matched {t:%b} {t.day}'


def match_payload(m, viewer, request=None):
    from apps.chats.models import ChatMessage
    from apps.social.feed import person
    other = m.other(viewer)
    said_hi = bool(m.chat_id and ChatMessage.objects.filter(chat_id=m.chat_id, sender=viewer,
                                                            removed_at=None).exists())
    idea = (event_idea(m.suggested_event, viewer, other) if m.suggested_event_id
            else first_date_idea(viewer, other))
    return {
        'id': m.id,
        'person': person(other, request),
        'age': age_of(other),
        'neighborhood': other.neighborhood,
        'matched': _matched_label(m, viewer),
        'chat_id': m.chat_id,
        'steps': {'matched': True, 'said_hi': said_hi or bool(m.suggested_event_id),
                  'planned': bool(m.suggested_event_id), 'met': m.flag(viewer, 'met')},
        'idea': idea,
        'suggested': bool(m.suggested_event_id),
        'suggested_by_me': m.suggested_by_id == viewer.id,
        # They turned Romantic off: the match and its chat are on hold.
        'on_hold': not opted_in(other),
    }


def meantime(user, request=None, n=2):
    from apps.social.community import visible_events
    tz = safe_zone(user.timezone)
    qs = (visible_events(user).filter(start_time__gt=timezone.now()).exclude(kind='featured')
          .order_by('start_time')[:n])
    return [{'id': e.id, 'title': e.title,
             'when': f'{e.start_time.astimezone(tz):%a %-I:%M %p}'} for e in qs]


def state(user, request=None, now=None):
    """Everything the A Good Match screen needs, in one shape."""
    now = now or timezone.now()
    if not opted_in(user):
        return {'mode': 'off'}
    p = MatchProfile.of(user)
    out = {'profile_ready': bool(p.gender), 'paused': user.match_paused}
    m = holding(user)
    if m:
        out['match'] = match_payload(m, user, request)
        out['mode'] = 'met' if (m.flag(user, 'met') and not m.flag(user, 'kept')) else 'locked'
        return out
    if p.cooling:
        hours = max(1, round((p.cooldown_until - now).total_seconds() / 3600))
        until = local_now(user, p.cooldown_until)
        return dict(out, mode='cool', cool={
            'until': p.cooldown_until.isoformat(),
            'until_label': (f'tomorrow at {until:%-I:%M %p}' if until.date() > local_now(user, now).date()
                            else f'at {until:%-I:%M %p}'),
            'hours': hours,
            'meantime': meantime(user, request)})
    if user.match_paused:
        return dict(out, mode='paused')
    left = max(0, DAILY - decided_today(user, now))
    nxt = None
    if left:
        found = candidates(user, now)[:1]
        if found:
            nxt = card(user, *found[0], request=request)
    return dict(out, mode='browse', browse={'card': nxt, 'left_today': left if nxt else 0})


def new_today(user):
    """'3 new matches today' on You: profiles still waiting today."""
    try:
        if not available(user):
            return 0
        left = max(0, DAILY - decided_today(user))
        return min(left, len(candidates(user))) if left else 0
    except Exception:
        log.exception('new_today failed')
        return 0


# ----------------------------------------------------------------- actions

def _first(u):
    return u.first_name or (u.display_name or 'Someone').split(' ')[0]


def decide(user, target_id, action, prompt='', note=''):
    """Like or pass on the profile being shown. Returns the Match if it's mutual."""
    from apps.users.models import User
    if action not in ('like', 'pass'):
        raise NotAllowed('action', 'Like or pass.')
    if not available(user):
        raise NotAllowed('locked', 'New matches are paused right now.', 409)
    if decided_today(user) >= DAILY:
        raise NotAllowed('done_today', 'That’s everyone for today.', 409)
    target = User.objects.filter(pk=target_id).first()
    if target is None or not any(c[0].id == target.id for c in candidates(user)):
        raise NotAllowed('gone', 'That profile isn’t available anymore.', 404)
    note = (note or '').strip()[:300]
    prompt = (prompt or '').strip()[:80]
    Decision.objects.update_or_create(actor=user, target=target, defaults={
        'action': action, 'prompt': prompt if action == 'like' else '', 'note': note if action == 'like' else '',
        'created_at': timezone.now()})
    if action == 'pass':
        return None
    theirs = Decision.objects.filter(actor=target, target=user, action='like').first()
    if not theirs or not available(target):
        return None
    return _lock(user, target, mine=Decision.objects.get(actor=user, target=target), theirs=theirs)


def _lock(user, target, mine, theirs):
    from apps.chats.models import Chat, ChatMember
    from apps.chats.services import send
    a, b = sorted([user, target], key=lambda u: u.id)
    with transaction.atomic():
        chat = Chat.objects.create(kind='match', pair_key=f'match:{a.id}:{b.id}:{int(timezone.now().timestamp())}')
        ChatMember.objects.create(chat=chat, user=a)
        ChatMember.objects.create(chat=chat, user=b)
        m = Match.objects.create(a=a, b=b, chat=chat)
    # Replies to prompts open the chat, the earlier one first.
    for d in sorted([theirs, mine], key=lambda d: d.created_at):
        if d.note:
            try:
                send(chat, d.actor, body=d.note, attachment='prompt', share={'prompt': d.prompt})
            except Exception:
                log.exception('could not post the prompt reply')
    _notify(target, user, [['You and ', False], [_first(user), True], [' are a match. Say hi when you’re ready.',
                                                                       False]])
    return m


def _notify(recipient, actor, parts, link='/match'):
    try:
        from apps.notifications.services import notify
        notify(recipient, 'match', parts, actor=actor, link=link, push_title='A Good Match')
    except Exception:
        log.exception('match notification failed')


def get_match(user, pk):
    m = Match.involving(user).select_related('a', 'b', 'chat', 'suggested_event').filter(pk=pk).first()
    if m is None or m.state == 'ended' or not opted_in(user):
        raise NotAllowed('not_found', 'This match isn’t available.', 404)
    return m


def suggest(user, m, event_id=None):
    """Suggest a first meetup: it shows on both sides and as a card in the chat."""
    from apps.chats.models import ChatMessage
    from apps.chats.services import send
    from apps.events.models import Event
    other = m.other(user)
    if event_id:
        e = Event.objects.filter(pk=event_id, is_active=True, is_cancelled=False, who_can_join='anyone') \
            .exclude(kind='featured').first()
    else:
        idea = first_date_idea(user, other)
        e = Event.objects.filter(pk=idea['id']).first() if idea else None
    if e is None:
        raise NotAllowed('event', 'That event isn’t available.', 404)
    if m.chat_id:
        ChatMessage.objects.filter(chat_id=m.chat_id, attachment='meetup', removed_at=None) \
            .update(removed_at=timezone.now(), removed_by=user)
    m.suggested_event, m.suggested_by = e, user
    m.save(update_fields=['suggested_event', 'suggested_by'])
    if m.chat_id and not m.chat.is_closed and opted_in(other):
        idea = event_idea(e, user)
        send(m.chat, user, attachment='meetup', share={'event': e.id, 'title': e.title, 'when': idea['short']})
    return m


def unsuggest(user, m):
    from apps.chats.models import ChatMessage
    if m.suggested_by_id != user.id:
        raise NotAllowed('not_yours', 'Only the one who suggested it can take it back.', 403)
    if m.chat_id:
        ChatMessage.objects.filter(chat_id=m.chat_id, sender=user, attachment='meetup', removed_at=None) \
            .update(removed_at=timezone.now(), removed_by=user)
    m.suggested_event = m.suggested_by = None
    m.save(update_fields=['suggested_event', 'suggested_by'])
    return m


def met_up(user, m):
    fields = [m.set_flag(user, 'met', True)]
    if m.state == 'locked':
        m.state, m.met_at = 'met', timezone.now()
        fields += ['state', 'met_at']
    m.save(update_fields=fields)
    return m


def keep(user, m):
    m.save(update_fields=[m.set_flag(user, 'kept', True), m.set_flag(user, 'open', False)])
    return m


def open_up(user, m):
    """After meeting up: open up to new matches. The other person isn't told.
    Their chat stays open."""
    if not m.flag(user, 'met'):
        raise NotAllowed('not_met', 'Tap "We met up" first.', 409)
    m.save(update_fields=[m.set_flag(user, 'open', True)])
    return m


def move_on(user, m, reason='move_on'):
    """End the match. The chat closes; the mover waits until 9:00 AM tomorrow
    (unless the other person had already stepped away or was blocked); the
    other person gets a kind note."""
    other = m.other(user)
    now = timezone.now()
    with transaction.atomic():
        m.state, m.ended_at, m.ended_by = 'ended', now, user
        m.save(update_fields=['state', 'ended_at', 'ended_by'])
        if m.chat_id:
            type(m.chat).objects.filter(pk=m.chat_id).update(closes_at=now)
        if reason == 'move_on' and opted_in(other):
            p = MatchProfile.of(user)
            p.cooldown_until = tomorrow_nine(user, now)
            p.save(update_fields=['cooldown_until'])
    if reason == 'move_on' and opted_in(other):
        _notify(other, None, [['Your match with ', False], [_first(user), True],
                              [' has ended. Thanks for giving it a real shot. New matches arrive each morning.',
                               False]])
    return m


def end_for_block(blocker, blocked):
    """Blocking a match ends it at once, with no cooldown and no note."""
    for m in Match.involving(blocker).filter(state__in=('locked', 'met')).filter(
            a_id__in=(blocker.id, blocked.id), b_id__in=(blocker.id, blocked.id)):
        move_on(blocker, m, reason='block')


def chat_open(chat):
    """Can anyone write in this match chat? Not after moving on, and not while
    one of them has turned Romantic off."""
    m = Match.objects.filter(chat=chat).select_related('a', 'b').first()
    return bool(m and m.state != 'ended' and opted_in(m.a) and opted_in(m.b))


def quick_replies(m, viewer):
    if m.suggested_event_id:
        tz = safe_zone(viewer.timezone)
        day = m.suggested_event.start_time.astimezone(tz).strftime('%A')
        return [f'See you {day}', 'Coffee after?', 'Running 5 min late']
    return ['Hi! How was your week?', 'What’s your favorite route?', 'Want to plan a meetup?']


# --------------------------------------------------------------- the profile

def profile_payload(user):
    p = MatchProfile.of(user)
    return {
        'gender': p.gender or None,
        'show_me': p.show_me,
        'age_min': p.age_min,
        'age_max': p.age_max,
        'max_miles': p.max_miles,
        'prompts': p.prompts or [],
        'pace_note': p.pace_note,
        'prompt_options': PROMPTS,
        'age': age_of(user),
        'genders': [g for g, _ in MatchProfile.GENDERS],
    }


def update_profile(user, d):
    p = MatchProfile.of(user)
    if 'gender' in d:
        if d['gender'] not in ('', None) and d['gender'] not in dict(MatchProfile.GENDERS):
            raise NotAllowed('gender', 'Pick one.')
        p.gender = d['gender'] or ''
    if 'show_me' in d:
        if d['show_me'] not in MatchProfile.SHOW_ME:
            raise NotAllowed('show_me', 'Pick who to show.')
        p.show_me = d['show_me']
    lo, hi = d.get('age_min', p.age_min), d.get('age_max', p.age_max)
    try:
        lo, hi = int(lo), int(hi)
    except (TypeError, ValueError):
        raise NotAllowed('age', 'Ages are numbers.')
    if not (21 <= lo <= hi <= 99):
        raise NotAllowed('age', 'Pick an age range from 21 up.')
    p.age_min, p.age_max = lo, hi
    if 'max_miles' in d:
        try:
            p.max_miles = max(1, min(100, int(d['max_miles'])))
        except (TypeError, ValueError):
            raise NotAllowed('max_miles', 'Distance is a number.')
    if 'prompts' in d:
        rows = []
        for x in (d['prompts'] or [])[:MAX_PROMPTS]:
            q, a = (x.get('q') or '').strip(), (x.get('a') or '').strip()
            if not q and not a:
                continue
            if q not in PROMPTS:
                raise NotAllowed('prompts', 'Pick a prompt from the list.')
            if not a:
                raise NotAllowed('prompts', 'Answer the prompt, or remove it.')
            rows.append({'q': q, 'a': a[:150]})
        p.prompts = rows
    if 'pace_note' in d:
        p.pace_note = (d['pace_note'] or '').strip()[:40]
    p.save()
    return profile_payload(user)
