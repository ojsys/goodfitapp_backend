"""Small geometry helpers (meters, degrees)."""

import math

R = 6371000.0


def dist(a, b):
    """Haversine meters between (lat, lng, ...) points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(h)))


def line_length(pts):
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def resample(pts, step):
    """Points every `step` meters along a line (keeps both ends)."""
    if len(pts) < 2:
        return list(pts)
    out = [pts[0]]
    carry = 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        d = dist(a, b)
        if d == 0:
            continue
        pos = step - carry
        while pos <= d:
            f = pos / d
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            pos += step
        carry = d - (pos - step)
    if dist(out[-1], pts[-1]) > 1:
        out.append(pts[-1])
    return out


def bbox(pts, pad_m=0):
    lats, lngs = [p[0] for p in pts], [p[1] for p in pts]
    dlat = pad_m / 111320.0
    dlng = pad_m / (111320.0 * max(0.2, math.cos(math.radians(sum(lats) / len(lats)))))
    return min(lats) - dlat, max(lats) + dlat, min(lngs) - dlng, max(lngs) + dlng
