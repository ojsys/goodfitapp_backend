"""Members set to Plus by hand before subscriptions existed keep it, as
Plus given by the team (otherwise the hourly check would end it)."""

from django.db import migrations


def forwards(apps, schema_editor):
    User = apps.get_model('users', 'User')
    Subscription = apps.get_model('plus', 'Subscription')
    for u in User.objects.filter(plan='plus'):
        if not Subscription.objects.filter(user=u).exists():
            Subscription.objects.create(user=u, store='comp', product='comp', status='active',
                                        will_renew=False, note='Plus before subscriptions (Phase 9)')


class Migration(migrations.Migration):
    dependencies = [('plus', '0001_initial'), ('users', '0007_user_default_visibility_user_match_paused_and_more')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
