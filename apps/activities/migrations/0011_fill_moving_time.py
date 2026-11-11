"""Activities logged without a moving time count their duration in totals
(You > season, Training), the same as their feed card shows."""

from django.db import migrations
from django.db.models import F


def forwards(apps, schema_editor):
    Activity = apps.get_model('activities', 'Activity')
    Activity.objects.filter(moving_time__isnull=True, duration__gt=0).update(moving_time=F('duration') * 60)


class Migration(migrations.Migration):
    dependencies = [('activities', '0010_activity_best_efforts')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
