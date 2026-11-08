"""Segment efforts, PRs, leaderboards and the segment page (Perf-Segment)."""

from datetime import datetime, time

from django.db.models import Count, Min, Q
from django.utils import timezone

from apps.safety.visibility import blocked_ids
from apps.social.feed import person
from apps.social.models import ClubMembership, Follow
from apps.users.age_gate import safe_zone

from .matching import best_efforts, find_efforts
from .models import Segment, SegmentEffort

MI = 1609.344


def clock(sec):
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def ordinal(n):
    return f'{n}{"th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")}'


def club_member_ids(user):
    clubs = ClubMembership.objects.filter(user=user).values('club_id')
    return set(ClubMembership.objects.filter(club_id__in=clubs).values_list('user_id', flat=True)) | {user.id}


# ------------------------------------------------------------- recording

def record_efforts(act):
    """Match a saved activity to segments, store efforts and best efforts,
    tell anyone who just got passed, and update challenges."""
    if act.type not in ('ride', 'run'):
        return []
    pts = act.track_points()
    made = []
    for seg, start, secs, speed in find_efforts(act.type, pts):
        prev = SegmentEffort.objects.filter(segment=seg, user=act.user).aggregate(m=Min('elapsed_s'))['m']
        e = SegmentEffort.objects.create(segment=seg, activity=act, user=act.user, elapsed_s=secs, start_at=start,
                                         avg_speed=speed, is_pr=prev is None or secs < prev,
                                         private=act.visibility == 'me')
        made.append(e)
        if e.is_pr and not e.private:
            _tell_passed(seg, act.user, secs, prev)
    best = best_efforts(act.type, pts)
    if best != (act.best_efforts or {}):
        type(act).objects.filter(pk=act.pk).update(best_efforts=best)
        act.best_efforts = best
    return made


def _tell_passed(seg, actor, new_time, old_best):
    """'Alex is 2 seconds ahead of you on Park Drive Sprint. Beat 1:22 to move up to 3rd.'
    Only club mates who were ahead of the actor before and are behind now."""
    from apps.notifications.services import B, T, notify
    mates = club_member_ids(actor) - {actor.id}
    if not mates:
        return
    bests = (SegmentEffort.objects.filter(segment=seg, user_id__in=mates | {actor.id}, private=False,
                                          user__is_active=True)
             .values('user_id').annotate(best=Min('elapsed_s')).order_by('best'))
    board = list(bests)
    rank = next((i + 1 for i, r in enumerate(board) if r['user_id'] == actor.id), None)
    for r in board:
        if r['user_id'] == actor.id:
            continue
        if new_time < r['best'] and (old_best is None or old_best >= r['best']):
            from apps.users.models import User
            u = User.objects.filter(pk=r['user_id']).first()
            gap = r['best'] - new_time
            notify(u, 'segment', [B(actor.first_name or 'Someone'), T(f' is {gap} second{"s" if gap != 1 else ""} '
                                                                       'ahead of you on '),
                                   B(seg.name), T(f'. Beat {clock(new_time)} to move up to {ordinal(rank)}.')],
                   actor=actor, link=f'/segments/{seg.id}')


def effort_note(seg, user, secs, before=None, exclude_id=None):
    """(badge, note) for a time: ('PR', 'New PR'), ('2', '2nd best, 4s off PR'), (None, '')."""
    others = SegmentEffort.objects.filter(segment=seg, user=user)
    if exclude_id:
        others = others.exclude(pk=exclude_id)
    if before is not None:
        others = others.filter(created_at__lt=before)
    times = sorted(others.values_list('elapsed_s', flat=True))
    if not times or secs < times[0]:
        return 'PR', 'New PR'
    rank = 1 + sum(1 for t in times if t < secs)
    if rank <= 3:
        gap = secs - times[0]
        return str(rank), f'{ordinal(rank)} best, {gap}s off PR'
    return None, ''


def achievements(kind, points, user):
    """For the Save screen, before uploading: ['New PR on Zoo Hill', ...]."""
    out = []
    for seg, _, secs, _ in find_efforts(kind, points):
        badge, note = effort_note(seg, user, secs)
        if badge == 'PR':
            out.append({'kind': 'pr', 'segment': seg.id, 'text': f'New PR on {seg.name}'})
        elif badge:
            gap = note.split(', ')[1].replace(' off PR', '')
            out.append({'kind': 'rank', 'segment': seg.id,
                        'text': f'{seg.name}: {ordinal(int(badge))} best time, {gap} off your PR'})
    return out


def activity_segments(act, viewer):
    """The Segments list on an activity (Core-ActivityDetail)."""
    if act.user_id != viewer.id and act.visibility == 'me':
        return []
    rows = []
    for e in act.segment_efforts.select_related('segment').order_by('start_at'):
        badge, note = effort_note(e.segment, act.user, e.elapsed_s, before=e.created_at, exclude_id=e.id)
        if badge == 'PR' and not e.is_pr:
            badge, note = 'PR', 'Best time'
        dist = f'{e.segment.distance_m / MI:.1f} mi' if viewer.units != 'km' else f'{e.segment.distance_m / 1000:.1f} km'
        rows.append({'id': e.segment_id, 'name': e.segment.name, 'time': clock(e.elapsed_s), 'badge': badge,
                     'meta': ' · '.join(x for x in [dist, note] if x)})
    return rows


# ----------------------------------------------------------- leaderboards

def _visible_efforts(seg, viewer):
    return (SegmentEffort.objects.filter(segment=seg, user__is_active=True)
            .filter(Q(private=False) | Q(user=viewer)).exclude(user_id__in=blocked_ids(viewer)))


def board(seg, viewer, scope='all', limit=50):
    qs = _visible_efforts(seg, viewer)
    tz = safe_zone(viewer.timezone)
    if scope == 'year':
        jan1 = datetime.combine(timezone.localtime(timezone.now(), tz).date().replace(month=1, day=1), time.min,
                                tzinfo=tz)
        qs = qs.filter(start_at__gte=jan1)
    elif scope == 'club':
        qs = qs.filter(user_id__in=club_member_ids(viewer))
    elif scope == 'following':
        qs = qs.filter(user_id__in=set(Follow.objects.filter(follower=viewer).values_list('followee_id', flat=True))
                       | {viewer.id})
    bests = list(qs.values('user_id').annotate(best=Min('elapsed_s')).order_by('best', 'user_id')[:limit])
    rows = []
    for i, b in enumerate(bests):
        e = qs.filter(user_id=b['user_id'], elapsed_s=b['best']).select_related('user').order_by('start_at').first()
        rows.append({'rank': i + 1, 'effort': e, 'user': e.user, 'time': b['best']})
    return rows


def _row(r, viewer, request):
    e = r['effort']
    local = timezone.localtime(e.start_at, safe_zone(viewer.timezone))
    speed = e.avg_speed * 2.23694 if viewer.units != 'km' else e.avg_speed * 3.6
    return {'rank': r['rank'], 'person': person(r['user'], request), 'is_me': r['user'].id == viewer.id,
            'time': clock(r['time']), 'meta': f'{local:%b} {local.day} · {speed:.1f} {"mph" if viewer.units != "km" else "km/h"}'}


def segment_page(seg, viewer, scope='all', request=None):
    tz = safe_zone(viewer.timezone)
    units = viewer.units
    club_board = board(seg, viewer, 'club', limit=500)
    has_club = ClubMembership.objects.filter(user=viewer).exists()
    record_rows = club_board if has_club else board(seg, viewer, 'all', limit=1)
    record = record_rows[0] if record_rows else None
    mine = list(SegmentEffort.objects.filter(segment=seg, user=viewer).order_by('-start_at')[:20])
    pr = min((e.elapsed_s for e in mine), default=None)
    my_rank = next((r['rank'] for r in club_board if r['user'].id == viewer.id), None)
    pr_effort = next((e for e in mine if e.elapsed_s == pr), None)

    chase = None
    if pr is not None and my_rank and my_rank > 1:
        ahead = club_board[my_rank - 2]
        gap = pr - ahead['time']
        chase = {'people': [person(viewer, request), person(ahead['user'], request)],
                 'title': f'Beat {clock(ahead["time"])} to pass {ahead["user"].first_name or "them"}',
                 'note': f'{gap}s faster than your PR moves you to {ordinal(my_rank - 1)}',
                 'from': clock(pr), 'to': clock(ahead['time']), 'target_s': ahead['time'],
                 'progress': round(ahead['time'] / pr, 3) if pr else 0}
    elif pr is None:
        target = record['time'] if record else None
        chase = {'people': [person(viewer, request)], 'title': 'Get on the board',
                 'note': 'Ride it once and your time shows up here.' if seg.kind != 'run' else
                         'Run it once and your time shows up here.',
                 'from': None, 'to': clock(target) if target else None, 'target_s': target, 'progress': 0}

    efforts = []
    for e in mine[:5]:
        local = timezone.localtime(e.start_at, tz)
        today = timezone.localtime(timezone.now(), tz).date()
        label = 'Today' if local.date() == today else f'{local:%b} {local.day}'
        efforts.append({'label': label, 'time': clock(e.elapsed_s), 'is_pr': e.elapsed_s == pr,
                        'delta': None if e.elapsed_s == pr else f'+{e.elapsed_s - pr}s'})

    spotlight = []
    if has_club:
        mates = club_member_ids(viewer) - blocked_ids(viewer)
        month_start = datetime.combine(timezone.localtime(timezone.now(), tz).date().replace(day=1), time.min, tzinfo=tz)
        vis = _visible_efforts(seg, viewer).filter(user_id__in=mates)
        best_now = dict(vis.filter(start_at__gte=month_start).values_list('user_id').annotate(m=Min('elapsed_s')))
        best_before = dict(vis.filter(start_at__lt=month_start).values_list('user_id').annotate(m=Min('elapsed_s')))
        gains = [(best_before[u] - t, u, best_before[u], t) for u, t in best_now.items()
                 if u in best_before and best_before[u] > t]
        from apps.users.models import User
        if gains:
            g, uid, old, new = max(gains)
            u = User.objects.get(pk=uid)
            spotlight.append({'label': 'Most Improved This Month', 'person': person(u, request),
                              'note': f'Cut {g}s, from {clock(old)} to {clock(new)}'})
        most = vis.values('user_id').annotate(n=Count('id')).order_by('-n').first()
        if most and most['n'] >= 3:
            u = User.objects.get(pk=most['user_id'])
            spotlight.append({'label': 'Most Attempts', 'person': person(u, request),
                              'note': f'{most["n"]} {"rides" if seg.kind != "run" else "runs"} through this stretch'})

    attempts = SegmentEffort.objects.filter(segment=seg).count()
    length = f'{seg.distance_m / MI:.2f}' if units != 'km' else f'{seg.distance_m / 1000:.2f}'
    elev = round(seg.elev_diff_m * 3.28084) if units != 'km' else round(seg.elev_diff_m)
    return {
        'id': seg.id,
        'name': seg.name,
        'kind': seg.kind,
        'meta': ' · '.join(x for x in [seg.area, f'{attempts:,} attempt{"s" if attempts != 1 else ""}'] if x),
        'stats': [{'label': 'Length', 'value': length, 'unit': 'mi' if units != 'km' else 'km'},
                  {'label': 'Avg Grade', 'value': f'{seg.avg_grade:.1f}', 'unit': '%'},
                  {'label': 'Elev Diff', 'value': f'{elev}', 'unit': 'ft' if units != 'km' else 'm'}],
        'line': [[p[0], p[1]] for p in seg.line],
        'profile': [p[2] for p in seg.line if len(p) > 2 and p[2] is not None],
        'record': ({'label': 'Club Record' if has_club else 'Record', 'time': clock(record['time']),
                    'person': person(record['user'], request)} if record else None),
        'pr': ({'time': clock(pr), 'note': _pr_note(pr_effort, tz, my_rank if has_club else None)}
               if pr is not None else None),
        'pr_s': pr,
        'chase': chase,
        'efforts': efforts,
        'spotlight': spotlight,
        'scope': scope,
        'leaderboard': [_row(r, viewer, request) for r in board(seg, viewer, scope)],
    }


def _pr_note(e, tz, club_rank):
    local = timezone.localtime(e.start_at, tz)
    bits = [f'{local:%b} {local.day}']
    if club_rank:
        bits.append(f'{ordinal(club_rank)} in club')
    return ' · '.join(bits)


def nearby(lat, lng, viewer, radius_m=15000):
    """Segments near the phone, with the member's PR, for live alerts."""
    d = radius_m / 111320.0
    qs = Segment.objects.filter(is_active=True, min_lat__lte=lat + d, max_lat__gte=lat - d,
                                min_lng__lte=lng + d * 1.5, max_lng__gte=lng - d * 1.5)[:60]
    prs = dict(SegmentEffort.objects.filter(segment__in=qs, user=viewer).values_list('segment_id')
               .annotate(m=Min('elapsed_s')))
    return [{'id': s.id, 'name': s.name, 'kind': s.kind, 'distance_m': s.distance_m,
             'line': [[p[0], p[1]] for p in s.line], 'pr_s': prs.get(s.id)} for s in qs]
