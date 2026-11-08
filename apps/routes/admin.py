from django.contrib import admin

from .models import Route, RouteSave


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ['name', 'owner', 'club', 'best_for', 'visibility', 'club_favorite']
    raw_id_fields = ['owner']


admin.site.register(RouteSave)
