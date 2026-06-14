from django.db import migrations, models


def copy_authorization_state(apps, schema_editor):
    DataSource = apps.get_model("charging", "DataSource")
    for source in DataSource.objects.all():
        source.is_authorized = not source.is_mock
        source.save(update_fields=["is_authorized"])


class Migration(migrations.Migration):

    dependencies = [
        ("charging", "0002_production_safe_defaults"),
    ]

    operations = [
        migrations.AddField(
            model_name="datasource",
            name="is_authorized",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(copy_authorization_state, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="datasource",
            name="is_mock",
        ),
    ]
