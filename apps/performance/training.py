"""Training (Perf-Training): load by week, month, year or all time, consistency,
fitness trend, personal records."""

from datetime import date, datetime, time, timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from apps.activities.models import Activity
from apps.users.age_gate import safe_zone

from . import challenges as ch_svc
from .models import ChallengeEntry
from .segments import clock

MI, FT = 1609.344, 3.28084
MONTHS = 'JFMAMJJASOND'


def hours_minutes(sec):
    """'2:18' (hours and minutes), as the design shows time totals."""
    m = int(sec) // 60
    return f'{m // 60}:{m % 60:02d}'


def _midnight(d, tz):
    return datetime.combine(d, time.min, tzinfo=tz)


def _range(kind, today):
    """(start, end, buckets[(label, start, end, is_today, is_future)], previous (start, end) up to the same point)."""
    if kind == 'week':
        start = today - timedelta(days=today.weekday())
        days = [start + timedelta(days=i) for i in range(7)]
        buckets = [('MTWTFSS'[i], d, d + timedelta(days=1), d == today, d > today) for i, d in enumerate(days)]
        prev = (start - timedelta(days=7), today - timedelta(days=6))
        return start, start + timedelta(days=7), buckets, prev
    if kind == 'month':
        start = today.replace(day=1)
        nxt = (start + timedelta(days=32)).replace(day=1)
        buckets, d, n = [], start, 1
        while d < nxt:
            e = min(nxt, d + timedelta(days=7 - d.weekday()))
            buckets.append((f'W{n}', d, e, d <= today < e, d > today))
            d, n = e, n + 1
        pstart = (start - timedelta(days=1)).replace(day=1)
        return start, nxt, buckets, (pstart, pstart + (today - start) + timedelta(days=1))
    if kind == 'year':
        start = today.replace(month=1, day=1)
        buckets = []
        for m in range(1, 13):
            a = date(today.year, m, 1)
            b = date(today.year + (m == 12), 1 if m == 12 else m + 1, 1)
            buckets.append((MONTHS[m - 1], a, b, a <= today < b, a > today))
        pstart = start.replace(year=start.year - 1)
        return start, date(today.year + 1, 1, 1), buckets, (pstart, today.replace(year=today.year - 1) + timedelta(days=1))
    return None


def _label(kind, start, end, today):
    if kind == 'week':
        last = end - timedelta(days=1)
        return f'{start:%b} {start.day} – {last:%b} {last.day}' if start.month != last.month else \
            f'{start:%b} {start.day} – {last.day}'
    if kind == 'month':
        return f'{today:%B %Y}'
    if kind == 'year':
        return f'{today.year}'
    return 'All time'


def summary(user, kind='week', sport=None):
    tz = safe_zone(user.timezone)
    today = timezone.localtime(timezone.now(), tz).date()
    acts = Activity.objects.filter(user=user)
    if sport:
        acts = acts.filter(type=sport)
    km = user.units == 'km'
    f = 1000 if km else MI

    if kind == 'all':
        first = acts.order_by('start_time').values_list('start_time', flat=True).first()
        y0 = timezone.localtime(first, tz).year if first else today.year
        buckets = [(str(y), date(y, 1, 1), date(y + 1, 1, 1), y == today.year, False) for y in range(y0, today.year + 1)]
        start, end, prev = date(y0, 1, 1), date(today.year + 1, 1, 1), None
    else:
        start, end, buckets, prev = _range(kind, today)

    period = acts.filter(start_time__gte=_midnight(start, tz), start_time__lt=_midnight(end, tz))
    agg = period.aggregate(d=Sum('distance'), t=Sum('moving_time'), e=Sum('elevation_gain'))
    total = (agg['d'] or 0) / f
    bars = []
    for label, a, b, is_today, future in buckets:
        d = period.filter(start_time__gte=_midnight(a, tz), start_time__lt=_midnight(b, tz)) \
            .aggregate(d=Sum('distance'))['d'] or 0
        bars.append({'label': label, 'value': round(d / f, 2), 'today': is_today, 'future': future})
    change = None
    if prev:
        before = acts.filter(start_time__gte=_midnight(prev[0], tz), start_time__lt=_midnight(prev[1], tz)) \
            .aggregate(d=Sum('distance'))['d'] or 0
        if before:
            change = round(((agg['d'] or 0) - before) / before * 100)
    word = {'week': 'last week', 'month': 'last month', 'year': 'last year'}.get(kind)
    return {
        'range': kind,
        'label': _label(kind, start, end, today),
        'total': round(total, 1),
        'unit': 'km' if km else 'mi',
        'total_note': 'so far' if kind != 'all' else 'all time',
        'change': change,
        'change_label': f'{"+" if change >= 0 else ""}{change}% vs {word}' if change is not None else None,
        'bars': bars,
        'stats': [
            {'label': 'Activities', 'value': f'{period.count():,}'},
            {'label': 'Time', 'value': hours_minutes(agg['t'] or 0)},
            {'label': 'Elev Gain', 'value': f'{round((agg["e"] or 0) * (1 if km else FT)):,}', 'unit': 'm' if km else 'ft'},
        ],
    }


def consistency(user):
    """Week streak, the last 12 weeks shaded by active days, and this week
    against the member's days-a-week goal (4 unless a challenge says otherwise)."""
    tz = safe_zone(user.timezone)
    today = timezone.localtime(timezone.now(), tz).date()
    monday = today - timedelta(days=today.weekday())
    first = monday - timedelta(weeks=104)
    days = {timezone.localtime(t, tz).date() for t in Activity.objects.filter(
        user=user, start_time__gte=_midnight(first, tz)).values_list('start_time', flat=True)}
    weeks = []
    for k in range(11, -1, -1):
        wk = monday - timedelta(weeks=k)
        weeks.append(sum(1 for i in range(7) if wk + timedelta(days=i) in days))
    streak, wk = 0, monday if weeks[-1] else monday - timedelta(weeks=1)
    while any(wk + timedelta(days=i) in days for i in range(7)):
        streak += 1
        wk -= timedelta(weeks=1)
    goal = ChallengeEntry.objects.filter(user=user, challenge__kind='days_per_week',
                                         challenge__in=ch_svc.active()).values_list('challenge__target', flat=True).first()
    goal = int(goal or 4)
    return {'streak_weeks': streak, 'weeks': weeks, 'this_week': weeks[-1], 'goal': goal,
            'goal_line': f'{weeks[-1]} of {goal} days this week'}


def trend(user):
    """Weekly moving time for 12 weeks. Building / Holding steady / Easing off."""
    tz = safe_zone(user.timezone)
    today = timezone.localtime(timezone.now(), tz).date()
    monday = today - timedelta(days=today.weekday())
    points, months = [], []
    for k in range(11, -1, -1):
        wk = monday - timedelta(weeks=k)
        secs = Activity.objects.filter(user=user, start_time__gte=_midnight(wk, tz),
                                       start_time__lt=_midnight(wk + timedelta(days=7), tz)) \
            .aggregate(t=Sum('moving_time'))['t'] or 0
        points.append(round(secs / 3600, 2))
        months.append(f'{wk:%b}')
    recent, before = sum(points[-4:]) / 4, sum(points[-8:-4]) / 4
    if before == 0 and recent == 0:
        state = 'Getting started'
    elif before == 0 or recent >= before * 1.1:
        state = 'Building'
    elif recent <= before * 0.9:
        state = 'Easing off'
    else:
        state = 'Holding steady'
    ticks = []
    for i, m in enumerate(months):
        if i == 0 or m != months[i - 1]:
            ticks.append({'index': i, 'label': m})
    return {'state': state, 'hours': points, 'ticks': ticks, 'label': 'Last 12 weeks'}


def records(user, sport):
    """Personal Records for the member's main sport."""
    tz = safe_zone(user.timezone)
    km = user.units == 'km'
    acts = Activity.objects.filter(user=user, type=sport)

    def when(a):
        t = timezone.localtime(a.start_time, tz)
        return f'{t:%b} {t.day}'

    out = []
    longest = acts.order_by('-distance').first()
    if longest and longest.distance:
        out.append({'label': f'Longest {"Ride" if sport == "ride" else "Run"}', 'when': when(longest),
                    'value': f'{longest.distance / (1000 if km else MI):.1f} {"km" if km else "mi"}',
                    'activity': longest.id})
    for label in (['10 mi', '40 km'] if sport == 'ride' else ['5K', '10K', 'Half']):
        best = None
        for a in acts.exclude(best_efforts={}).only('id', 'start_time', 'best_efforts'):
            s = (a.best_efforts or {}).get(label)
            if s and (best is None or s < best[0]):
                best = (s, a)
        if best:
            out.append({'label': f'Fastest {label}', 'when': when(best[1]), 'value': clock(best[0]),
                        'activity': best[1].id})
    climb = acts.order_by('-elevation_gain').first()
    if climb and climb.elevation_gain:
        out.append({'label': 'Biggest Climb', 'when': when(climb),
                    'value': f'{round(climb.elevation_gain * (1 if km else FT)):,} {"m" if km else "ft"}',
                    'activity': climb.id})
    return out


def main_sport(user):
    top = (Activity.objects.filter(user=user, type__in=['ride', 'run']).values('type')
           .annotate(n=Count('id')).order_by('-n').first())
    return top['type'] if top else 'ride'


def page(user, kind='week', sport=None, request=None):
    sport_for_records = sport if sport in ('ride', 'run') else main_sport(user)
    chal = ch_svc.page(user, request)
    joined = ([chal['featured']] if chal['featured'] and chal['featured']['joined'] else []) + chal['running']
    plus = user.plan == 'plus'
    return {
        'summary': summary(user, kind, sport if sport in ('ride', 'run') else None),
        'consistency': consistency(user),
        'challenge': ({'top': joined[0], 'more': len(joined) - 1} if joined else None),
        # Deeper insights are part of Plus.
        'trend': trend(user) if plus else {'locked': True},
        'records': records(user, sport_for_records),
        'sport': sport_for_records,
    }
