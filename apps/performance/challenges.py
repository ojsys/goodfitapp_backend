"""Challenges and trophies (Perf-Challenges)."""

from datetime import datetime, time, timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from apps.activities.models import Activity
from apps.safety.visibility import blocked_ids
from apps.social.feed import person
from apps.social.models import ClubMembership, Follow
from apps.users.age_gate import safe_zone

from .models import Challenge, ChallengeEntry, SegmentEffort, Trophy

MI, FT = 1609.344, 3.28084


def active():
    now = timezone.now()
    return Challenge.objects.filter(starts_at__lte=now, ends_at__gt=now)


def visible_to(user):
    """Everyone's challenges plus your clubs' ones."""
    from django.db.models import Q
    clubs = ClubMembership.objects.filter(user=user).values('club_id')
    return active().filter(Q(club__isnull=True) | Q(club_id__in=clubs))


def _acts(ch, user):
    qs = Activity.objects.filter(user=user, start_time__gte=ch.starts_at, start_time__lt=ch.ends_at)
    if ch.activity_types:
        qs = qs.filter(type__in=ch.activity_types)
    return qs


def _week_start(user):
    tz = safe_zone(user.timezone)
    today = timezone.localtime(timezone.now(), tz).date()
    return datetime.combine(today - timedelta(days=today.weekday()), time.min, tzinfo=tz)


def progress(ch, user):
    """(done, target, unit) in display terms for this member."""
    km = user.units == 'km'
    if ch.kind == 'distance':
        m = _acts(ch, user).aggregate(d=Sum('distance'))['d'] or 0
        f = 1000 if km else MI
        return m / f, ch.target / f, 'km' if km else 'mi'
    if ch.kind == 'elevation':
        m = _acts(ch, user).aggregate(e=Sum('elevation_gain'))['e'] or 0
        f = 1 if km else FT
        return m * f, ch.target * f, 'm' if km else 'ft'
    if ch.kind == 'activities':
        return _acts(ch, user).count(), ch.target, 'activities'
    if ch.kind == 'days_per_week':
        tz = safe_zone(user.timezone)
        start = _week_start(user)
        days = {timezone.localtime(t, tz).date() for t in _acts(ch, user).filter(start_time__gte=start)
                .values_list('start_time', flat=True)}
        return len(days), ch.target, 'days'
    if ch.kind == 'segments':
        segs = list(ch.segments.values_list('id', flat=True))
        done = (SegmentEffort.objects.filter(user=user, segment_id__in=segs, start_at__gte=ch.starts_at,
                                             start_at__lt=ch.ends_at).values('segment_id').distinct().count())
        return done, len(segs) or ch.target, 'bridges' if 'ridge' in ch.title else 'segments'
    return 0, ch.target, ''


def _fmt(v, unit):
    if unit in ('mi', 'km'):
        return f'{v:,.0f}' if v >= 100 else f'{v:,.1f}'.rstrip('0').rstrip('.')
    return f'{round(v):,}'


def _weeks_in(ch, user):
    return max(1, (timezone.now() - ch.starts_at).days // 7 + 1)


def card(ch, user, request=None, entry=None, detail=False):
    done, target, unit = progress(ch, user)
    pct = min(100, int(done / target * 100)) if target else 0
    tz = safe_zone(user.timezone)
    days_left = max(0, (timezone.localtime(ch.ends_at, tz).date() - timezone.localtime(timezone.now(), tz).date()).days)
    month = timezone.localtime(ch.starts_at, tz).strftime('%B')
    if ch.kind == 'days_per_week':
        sub = f'Weekly streak · {_weeks_in(ch, user)} week{"s" if _weeks_in(ch, user) != 1 else ""} in'
        line = f'{_fmt(done, unit)} / {_fmt(target, unit)} days'
    else:
        sub = ch.subtitle or f'{month}{" · club challenge" if ch.club_id else ""}'
        line = f'{_fmt(done, unit)} / {_fmt(target, unit)} {unit}'
    out = {
        'id': ch.id, 'title': ch.title, 'subtitle': sub, 'kind': ch.kind, 'icon': ch.icon, 'color': ch.color,
        'pct': pct, 'progress_line': line, 'joined': entry is not None, 'completed': bool(entry and entry.completed_at),
        'days_left': days_left,
    }
    if detail:
        left = max(0.0, target - done)
        per_day = f' · {_fmt(left / days_left, unit)} {unit} a day to finish' if days_left and left and unit in (
            'mi', 'km', 'ft', 'm') else ''
        out.update({
            'eyebrow': f'Featured · {month}' if ch.featured else month,
            'of_line': f'{_fmt(done, unit)} of {_fmt(target, unit)} {unit}',
            'left_line': (f'{days_left} day{"s" if days_left != 1 else ""} left{per_day}' if days_left
                          else 'Last day'),
        })
        entrants = ChallengeEntry.objects.filter(challenge=ch, user__is_active=True).exclude(
            user_id__in=blocked_ids(user))
        out['joined_count'] = entrants.count()
        friends = set(Follow.objects.filter(follower=user).values_list('followee_id', flat=True))
        faces = sorted(entrants.select_related('user')[:200], key=lambda e: (e.user_id not in friends, e.joined_at))
        out['faces'] = [person(e.user, request) for e in faces if e.user_id != user.id][:5]
        out['rank'] = _rank(ch, user) if entry else None
    return out


def _rank(ch, user):
    """Place among entrants by progress (distance, climbing, activities)."""
    if ch.kind not in ('distance', 'elevation', 'activities'):
        return None
    ids = list(ChallengeEntry.objects.filter(challenge=ch).values_list('user_id', flat=True))
    qs = Activity.objects.filter(user_id__in=ids, start_time__gte=ch.starts_at, start_time__lt=ch.ends_at)
    if ch.activity_types:
        qs = qs.filter(type__in=ch.activity_types)
    agg = {'distance': Sum('distance'), 'elevation': Sum('elevation_gain'), 'activities': Count('id')}[ch.kind]
    totals = dict(qs.values_list('user_id').annotate(v=agg))
    mine = totals.get(user.id, 0) or 0
    return 1 + sum(1 for u, v in totals.items() if u != user.id and (v or 0) > mine)


def page(user, request=None):
    """Featured, Also Running, Browse all and the season's trophies."""
    chs = list(visible_to(user).prefetch_related('segments'))
    entries = {e.challenge_id: e for e in ChallengeEntry.objects.filter(user=user, challenge__in=chs)}
    featured = next((c for c in chs if c.featured), None)
    running = [c for c in chs if c.id in entries and c != featured]
    browse = [c for c in chs if c.id not in entries and c != featured]
    tz = safe_zone(user.timezone)
    year = timezone.localtime(timezone.now(), tz).year
    trophies = Trophy.objects.filter(user=user, earned_at__year=year)
    return {
        'featured': card(featured, user, request, entries.get(featured.id), detail=True) if featured else None,
        'running': [card(c, user, request, entries[c.id]) for c in running],
        'browse': [card(c, user, request) for c in browse],
        'trophies': {'label': f'{year} season', 'count': Trophy.objects.filter(user=user).count(),
                     'items': [{'label': t.label, 'month': timezone.localtime(t.earned_at, tz).strftime('%b')}
                               for t in trophies[:12]]},
    }


def update_for(user):
    """After an upload: finish any challenges now complete (trophy +
    notification)."""
    from apps.notifications.services import B, T, notify
    for entry in ChallengeEntry.objects.filter(user=user, completed_at__isnull=True,
                                               challenge__in=active()).select_related('challenge'):
        ch = entry.challenge
        done, target, _ = progress(ch, user)
        if ch.kind == 'days_per_week' or done < target:
            continue
        entry.completed_at = timezone.now()
        entry.save(update_fields=['completed_at'])
        Trophy.objects.create(user=user, challenge=ch, label=ch.trophy_label or ch.title[:20], earned_at=entry.completed_at)
        notify(user, 'challenge', [T('You finished '), B(ch.title), T('. It’s in your trophy case.')],
               link='/challenges')


def nudge_ending(now=None):
    """'52 miles to go on Ride 500 miles. You’re at 90% with 3 days left.' Once per entry."""
    from apps.notifications.services import B, T, notify
    now = now or timezone.now()
    sent = 0
    for entry in (ChallengeEntry.objects.filter(completed_at__isnull=True, nudged=False,
                                                challenge__ends_at__gt=now,
                                                challenge__ends_at__lte=now + timedelta(days=3, hours=12))
                  .exclude(challenge__kind='days_per_week').select_related('challenge', 'user')):
        ch, u = entry.challenge, entry.user
        done, target, unit = progress(ch, u)
        if done >= target or not u.is_active:
            continue
        days = max(1, (ch.ends_at - now).days)
        pct = int(done / target * 100) if target else 0
        unit_word = {'mi': 'miles', 'km': 'km', 'ft': 'feet', 'm': 'meters'}.get(unit, unit)
        if notify(u, 'challenge', [B(f'{_fmt(target - done, unit)} {unit_word} to go'), T(' on '), B(ch.title),
                                   T(f'. You’re at {pct}% with {days} day{"s" if days != 1 else ""} left.')],
                  link='/challenges'):
            sent += 1
        entry.nudged = True
        entry.save(update_fields=['nudged'])
    return sent
