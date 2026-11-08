from django.db import migrations

TYPES = {'Run': 'run', 'Cycle': 'ride', 'Walk': 'walk', 'Swim': 'swim', 'Yoga': 'yoga', 'Strength': 'strength'}
# Old app: public / followers / private.
VIS = {'public': 'everyone', 'private': 'me'}


def forwards(apps, schema_editor):
    for name in ('Activity', 'LiveActivity'):
        Model = apps.get_model('activities', name)
        for old, new in TYPES.items():
            Model.objects.filter(type=old).update(type=new)
    Activity = apps.get_model('activities', 'Activity')
    for old, new in VIS.items():
        Activity.objects.filter(visibility=old).update(visibility=new)


def backwards(apps, schema_editor):
    for name in ('Activity', 'LiveActivity'):
        Model = apps.get_model('activities', name)
        for old, new in TYPES.items():
            Model.objects.filter(type=new).update(type=old)
    Activity = apps.get_model('activities', 'Activity')
    for old, new in VIS.items():
        Activity.objects.filter(visibility=new).update(visibility=old)


class Migration(migrations.Migration):
    dependencies = [('activities', '0006_activity_club_activity_effort_activity_elapsed_time_and_more')]
    operations = [migrations.RunPython(forwards, backwards)]
