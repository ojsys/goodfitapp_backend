"""
Matching tracks to segments, and best efforts over standard distances.

A pass counts when the track comes within START_R of the segment's start,
later within START_R of its end, covers about the segment's length on the
way (MIN_FRAC..MAX_FRAC), and never strays more than CORRIDOR_M from the
segment line. Its time is the clock time between those two points.
Passes faster than a bike or runner can go are ignored ("Car rides don't
count toward segments").
"""

from datetime import datetime, timezone as dt_tz

from .geo import bbox, dist, line_length, resample

START_R = 30.0
CORRIDOR_M = 45.0
MIN_FRAC, MAX_FRAC = 0.85, 1.3
MAX_SPEED = {'ride': 22.0, 'run': 7.5}  # m/s (~79 km/h, ~27 km/h)

BEST_DISTANCES = {
    'ride': [('10 mi', 16093.4), ('40 km', 40000.0)],
    'run': [('5K', 5000.0), ('10K', 10000.0), ('Half', 21097.5)],
}


def _seconds(t):
    """Point time in seconds: epoch milliseconds (the app today) or an ISO
    string (older uploads). None if neither."""
    if isinstance(t, (int, float)):
        return t / 1000.0
    if isinstance(t, str):
        try:
            return datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()
        except ValueError:
            return None
    return None


def _timed(points):
    """[(lat, lng, t_seconds)] for points that have a time."""
    out = []
    for p in points:
        t = _seconds(p[3])
        if t is not None:
            out.append((p[0], p[1], t))
    return out


def _closest_runs(track, target, radius):
    """Indexes where the track passes closest to `target` within `radius`
    (one per pass)."""
    out, best, best_i = [], None, None
    for i, p in enumerate(track):
        d = dist(p, target)
        if d <= radius:
            if best is None or d < best:
                best, best_i = d, i
        elif best is not None:
            out.append(best_i)
            best = best_i = None
    if best is not None:
        out.append(best_i)
    return out


def _follows(track, i, j, checkpoints):
    """Does track[i..j] stay with the segment (every checkpoint near some
    track point, in order)?"""
    k = i
    for c in checkpoints:
        found = False
        while k <= j:
            if dist(track[k], c) <= CORRIDOR_M:
                found = True
                break
            k += 1
        if not found:
            return False
    return True


def passes(track, segment):
    """[(i, j, seconds, meters)] for each pass through `segment`."""
    seg_pts = [(p[0], p[1]) for p in segment.line]
    if len(seg_pts) < 2 or len(track) < 2:
        return []
    length = segment.distance_m or line_length(seg_pts)
    checkpoints = resample(seg_pts, max(40.0, length / 25))[1:-1]
    starts = _closest_runs(track, seg_pts[0], START_R)
    ends = _closest_runs(track, seg_pts[-1], START_R)
    cum = [0.0]
    for a, b in zip(track, track[1:]):
        cum.append(cum[-1] + dist(a, b))
    out, last_end = [], -1
    for i in starts:
        if i <= last_end:
            continue
        for j in ends:
            if j <= i:
                continue
            covered = cum[j] - cum[i]
            if covered > length * MAX_FRAC:
                break
            if covered < length * MIN_FRAC:
                continue
            if _follows(track, i, j, checkpoints):
                secs = track[j][2] - track[i][2]
                if secs > 0:
                    out.append((i, j, secs, covered))
                    last_end = j
                break
    return out


def candidates(track):
    from .models import Segment
    lo_lat, hi_lat, lo_lng, hi_lng = bbox(track, pad_m=50)
    return Segment.objects.filter(is_active=True, min_lat__lte=hi_lat, max_lat__gte=lo_lat,
                                  min_lng__lte=hi_lng, max_lng__gte=lo_lng)


def find_efforts(kind, points):
    """[(segment, start_at, seconds, avg_speed)] for a track, without saving."""
    track = _timed(points)
    if len(track) < 2:
        return []
    found = []
    for seg in candidates(track):
        if seg.kind != 'any' and seg.kind != kind:
            continue
        for i, j, secs, meters in passes(track, seg):
            speed = seg.distance_m / secs
            if speed > MAX_SPEED.get(kind, 22.0):
                continue
            found.append((seg, datetime.fromtimestamp(track[i][2], tz=dt_tz.utc), int(round(secs)), speed))
    return found


def best_efforts(kind, points):
    """{'10 mi': seconds, ...}: fastest stretch of each standard distance."""
    track = _timed(points)
    targets = BEST_DISTANCES.get(kind)
    if not targets or len(track) < 2:
        return {}
    cum = [0.0]
    for a, b in zip(track, track[1:]):
        cum.append(cum[-1] + dist(a, b))
    out = {}
    for label, meters in targets:
        if cum[-1] < meters:
            continue
        best, i = None, 0
        for j in range(len(track)):
            while cum[j] - cum[i + 1] >= meters if i + 1 <= j else False:
                i += 1
            if cum[j] - cum[i] >= meters:
                secs = track[j][2] - track[i][2]
                if secs > 0 and (best is None or secs < best):
                    best = secs
        if best:
            out[label] = int(round(best))
    return out
