"""Routes you made count as saved (You > Saved Routes showed 0 for them)."""

from django.db import migrations


def forwards(apps, schema_editor):
    Route = apps.get_model('routes', 'Route')
    RouteSave = apps.get_model('routes', 'RouteSave')
    have = set(RouteSave.objects.values_list('user_id', 'route_id'))
    RouteSave.objects.bulk_create([RouteSave(user_id=o, route_id=r)
                                   for r, o in Route.objects.values_list('id', 'owner_id') if (o, r) not in have])


class Migration(migrations.Migration):
    dependencies = [('routes', '0001_initial')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
