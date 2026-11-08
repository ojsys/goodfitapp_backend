"""Match existing activities to segments. Run after adding a segment:

    python manage.py match_segments              # every segment
    python manage.py match_segments --segment 3  # one segment

Safe to re-run: activities that already have an effort on a segment are
skipped for that segment. Best efforts are filled in where missing.
"""

from django.core.management.base import BaseCommand
from django.db.models import Min

from apps.activities.models import Activity
from apps.performance.matching import best_efforts, passes, MAX_SPEED, _timed
from apps.performance.models import Segment, SegmentEffort


class Command(BaseCommand):
    help = 'Match existing activities to segments.'

    def add_arguments(self, parser):
        parser.add_argument('--segment', type=int)

    def handle(self, *args, **o):
        from datetime import datetime, timezone as dt_tz
        segs = Segment.objects.filter(is_active=True)
        if o.get('segment'):
            segs = segs.filter(pk=o['segment'])
        made = filled = 0
        for seg in segs:
            kinds = ['ride', 'run'] if seg.kind == 'any' else [seg.kind]
            acts = (Activity.objects.filter(type__in=kinds).exclude(segment_efforts__segment=seg)
                    .filter(start_latitude__isnull=False).order_by('start_time'))
            for act in acts.iterator():
                track = _timed(act.track_points())
                if len(track) < 2:
                    continue
                for i, j, secs, _ in passes(track, seg):
                    speed = seg.distance_m / secs
                    if speed > MAX_SPEED.get(act.type, 22.0):
                        continue
                    prev = SegmentEffort.objects.filter(segment=seg, user=act.user).aggregate(m=Min('elapsed_s'))['m']
                    SegmentEffort.objects.create(segment=seg, activity=act, user=act.user, elapsed_s=int(round(secs)),
                                                 start_at=datetime.fromtimestamp(track[i][2], tz=dt_tz.utc),
                                                 avg_speed=speed, is_pr=prev is None or secs < prev,
                                                 private=act.visibility == 'me')
                    made += 1
        for act in Activity.objects.filter(type__in=['ride', 'run'], best_efforts={}).iterator():
            best = best_efforts(act.type, act.track_points())
            if best:
                Activity.objects.filter(pk=act.pk).update(best_efforts=best)
                filled += 1
        self.stdout.write(f'{made} effort(s) added, best efforts filled on {filled} activit(ies)')
