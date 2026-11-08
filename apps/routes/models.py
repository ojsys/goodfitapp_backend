"""
Routes (Community-Routes, Community-CreateRoute): a drawn or recorded line
with best-for, distance, climb and visibility. Made by a member or a club.
"""

from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class Route(models.Model):
    BEST_FOR = [('ride', 'Ride'), ('run', 'Run'), ('walk', 'Walk'), ('hike', 'Hike')]
    VISIBILITY = [('public', 'Public'), ('club', 'Club'), ('me', 'Only me')]
    SURFACES = [('paved', 'Paved'), ('mixed', 'Mixed'), ('trail', 'Trail')]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='routes')
    club = models.ForeignKey('social.Club', on_delete=models.SET_NULL, null=True, blank=True, related_name='routes')
    name = models.CharField(max_length=120)
    best_for = models.CharField(max_length=10, choices=BEST_FOR, default='ride')
    # [[lat, lng], ...] the line to follow (snapped to roads when drawn).
    line = models.JSONField(default=list)
    # The points the member tapped, so the route can be edited later.
    waypoints = models.JSONField(default=list, blank=True)
    distance_m = models.FloatField(default=0)
    elevation_gain_m = models.FloatField(default=0)
    is_loop = models.BooleanField(default=False)
    surface = models.CharField(max_length=10, choices=SURFACES, default='paved')
    visibility = models.CharField(max_length=10, choices=VISIBILITY, default='public')
    # "Club favorite" label.
    club_favorite = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'routes'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class RouteSave(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_routes')
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='saves')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'route_saves'
        constraints = [models.UniqueConstraint(fields=['user', 'route'], name='route_save_once')]
