"""
Road snapping and elevation for Create a route.

Snapping uses an OSRM-compatible routing service per activity profile:
    ROUTING_URL_BIKE  e.g. https://routing.openstreetmap.de/routed-bike
    ROUTING_URL_FOOT  e.g. https://routing.openstreetmap.de/routed-foot
Elevation uses an OpenTopoData-compatible service:
    ELEVATION_URL     e.g. https://api.opentopodata.org/v1/srtm30m
Both are settings so production can point at a paid provider. If a service
is missing or down, snapping falls back to straight lines and climb to 0,
and the response says so.
"""

import json
import logging
import urllib.parse
import urllib.request

from django.conf import settings

from apps.social.privacy import haversine_m, sample

log = logging.getLogger(__name__)
TIMEOUT = 8


def line_distance(line):
    return sum(haversine_m(a, b) for a, b in zip(line, line[1:]))


def _get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'AGoodFit/1.0 (route builder)'})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (configured URL)
        return json.loads(r.read().decode())


def snap(points, best_for):
    """Road-following line through `points` ([[lat, lng], ...]).
    Returns (line, snapped: bool)."""
    base = getattr(settings, 'ROUTING_URL_BIKE' if best_for == 'ride' else 'ROUTING_URL_FOOT', '')
    if len(points) < 2:
        return [list(p) for p in points], False
    if not base:
        return [list(p) for p in points], False
    coords = ';'.join(f'{lng:.6f},{lat:.6f}' for lat, lng in points)
    profile = 'bike' if best_for == 'ride' else 'foot'
    url = f'{base.rstrip("/")}/route/v1/{profile}/{coords}?overview=full&geometries=geojson'
    try:
        data = _get(url)
        geom = data['routes'][0]['geometry']['coordinates']
        return [[round(lat, 6), round(lng, 6)] for lng, lat in geom], True
    except Exception as e:  # network, quota, no route
        log.warning('route snap failed: %s', e)
        return [list(p) for p in points], False


def elevation_gain(line):
    """Climb in meters along `line`, from up to 100 sampled points."""
    base = getattr(settings, 'ELEVATION_URL', '')
    if not base or len(line) < 2:
        return 0.0, False
    pts = sample(line, 100)
    locs = '|'.join(f'{lat:.5f},{lng:.5f}' for lat, lng in pts)
    try:
        data = _get(f'{base}?locations={urllib.parse.quote(locs, safe=",|.")}')
        alts = [r['elevation'] for r in data['results'] if r.get('elevation') is not None]
    except Exception as e:
        log.warning('elevation failed: %s', e)
        return 0.0, False
    gain, ref = 0.0, None
    for a in alts:
        if ref is None or a < ref:
            ref = a
        elif a - ref >= 2:
            gain += a - ref
            ref = a
    return gain, True


# Default moving speeds (m/s) for "Est. Time" when the member has no history.
DEFAULT_SPEED = {'ride': 6.7, 'run': 2.8, 'walk': 1.35, 'hike': 1.1}


def est_minutes(distance_m, best_for, user=None):
    speed = DEFAULT_SPEED.get(best_for, 1.35)
    if user is not None:
        from apps.activities.models import Activity
        recent = Activity.objects.filter(user=user, type=best_for, moving_time__gt=0, distance__gt=0) \
            .order_by('-start_time').values_list('distance', 'moving_time')[:20]
        d = sum(r[0] for r in recent)
        t = sum(r[1] for r in recent)
        if d > 1000 and t:
            speed = d / t
    return max(1, round(distance_m / speed / 60))
