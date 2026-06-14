# Generated manually after validating the Postgres CI path.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auththrottle",
            name="key",
            field=models.CharField(max_length=128, unique=True),
        ),
    ]
