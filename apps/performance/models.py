"""
Segments, challenges and trophies (Perf-Segment, Perf-Challenges).

A segment is a stretch of road or path. Every uploaded activity is matched
against nearby segments; each pass is a SegmentEffort with its time.
Leaderboards use each person's best effort. Efforts from activities set to
"Only me" never show to anyone else.
"""

from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class Segment(models.Model):
    KINDS = [('ride', 'Ride'), ('run', 'Run'), ('any', 'Any')]

    name = models.CharField(max_length=120)
    area = models.CharField(max_length=120, blank=True, help_text='e.g. Prospect Park, Brooklyn')
    kind = models.CharField(max_length=5, choices=KINDS, default='ride')
    # [[lat, lng, alt_or_null], ...] from start to end.
    line = models.JSONField(default=list)
    distance_m = models.FloatField(default=0)
    elev_diff_m = models.FloatField(default=0)
    avg_grade = models.FloatField(default=0, help_text='percent')
    start_lat = models.FloatField(default=0)
    start_lng = models.FloatField(default=0)
    end_lat = models.FloatField(default=0)
    end_lng = models.FloatField(default=0)
    # Bounding box, for finding segments near a track quickly.
    min_lat = models.FloatField(default=0, db_index=True)
    max_lat = models.FloatField(default=0, db_index=True)
    min_lng = models.FloatField(default=0)
    max_lng = models.FloatField(default=0)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'segments'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        from .geo import line_length
        pts = [p for p in self.line if len(p) >= 2]
        if len(pts) >= 2:
            self.start_lat, self.start_lng = pts[0][0], pts[0][1]
            self.end_lat, self.end_lng = pts[-1][0], pts[-1][1]
            self.min_lat, self.max_lat = min(p[0] for p in pts), max(p[0] for p in pts)
            self.min_lng, self.max_lng = min(p[1] for p in pts), max(p[1] for p in pts)
            self.distance_m = line_length(pts)
            alts = [p[2] for p in pts if len(p) > 2 and p[2] is not None]
            if len(alts) >= 2:
                self.elev_diff_m = max(alts) - min(alts)
                self.avg_grade = round((alts[-1] - alts[0]) / self.distance_m * 100, 1) if self.distance_m else 0
        super().save(*args, **kwargs)


class SegmentEffort(models.Model):
    segment = models.ForeignKey(Segment, on_delete=models.CASCADE, related_name='efforts')
    activity = models.ForeignKey('activities.Activity', on_delete=models.CASCADE, related_name='segment_efforts')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='segment_efforts')
    elapsed_s = models.PositiveIntegerField()
    start_at = models.DateTimeField()
    avg_speed = models.FloatField(default=0, help_text='m/s')
    # Was this the member's best on the segment when it was recorded?
    is_pr = models.BooleanField(default=False)
    # Private when the activity is "Only me".
    private = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'segment_efforts'
        indexes = [models.Index(fields=['segment', 'elapsed_s']), models.Index(fields=['segment', 'user'])]
        ordering = ['elapsed_s']


class Challenge(models.Model):
    KINDS = [
        ('distance', 'Total distance'), ('elevation', 'Total climbing'), ('activities', 'Number of activities'),
        ('days_per_week', 'Days a week'), ('segments', 'Ride a set of segments'),
    ]
    ICONS = [('bike', 'Bike'), ('mountain', 'Mountain'), ('bridge', 'Bridge'), ('run', 'Run'), ('trophy', 'Trophy')]
    COLORS = [('olive', 'Olive'), ('clay', 'Clay'), ('gold', 'Gold')]

    title = models.CharField(max_length=80)
    subtitle = models.CharField(max_length=120, blank=True, help_text='e.g. “Ride all 4 East River bridges”')
    kind = models.CharField(max_length=15, choices=KINDS)
    activity_types = models.JSONField(default=list, blank=True, help_text='["ride"]; empty means all')
    # Meters for distance/elevation; a count otherwise.
    target = models.FloatField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    featured = models.BooleanField(default=False)
    club = models.ForeignKey('social.Club', on_delete=models.CASCADE, null=True, blank=True, related_name='challenges')
    segments = models.ManyToManyField(Segment, blank=True, related_name='challenges')
    icon = models.CharField(max_length=10, choices=ICONS, default='bike')
    color = models.CharField(max_length=6, choices=COLORS, default='olive')
    trophy_label = models.CharField(max_length=20, blank=True, help_text='Short name in the trophy case, e.g. “500 mi”')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'challenges'
        ordering = ['-featured', 'ends_at']

    def __str__(self):
        return self.title


class ChallengeEntry(models.Model):
    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name='entries')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='challenge_entries')
    joined_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    nudged = models.BooleanField(default=False)

    class Meta:
        db_table = 'challenge_entries'
        constraints = [models.UniqueConstraint(fields=['challenge', 'user'], name='join_once')]


class Trophy(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='trophies')
    challenge = models.ForeignKey(Challenge, on_delete=models.SET_NULL, null=True, related_name='trophies')
    label = models.CharField(max_length=20)
    earned_at = models.DateTimeField()

    class Meta:
        db_table = 'trophies'
        ordering = ['-earned_at']
