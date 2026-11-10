from django.apps import AppConfig
from django.db.models.signals import post_migrate


class StaffConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.staff'
    verbose_name = 'Staff dashboard'

    def ready(self):
        from django.contrib import admin

        from . import roles
        admin.site.site_header = 'A Good Fit admin'
        admin.site.site_title = 'A Good Fit admin'
        admin.site.index_title = 'Every record in the app'
        admin.site.site_url = '/staff/'  # "View site" goes to the staff dashboard
        # Listed last in INSTALLED_APPS, so every app's permissions exist by now.
        post_migrate.connect(roles.sync, sender=self, dispatch_uid='staff-roles')
