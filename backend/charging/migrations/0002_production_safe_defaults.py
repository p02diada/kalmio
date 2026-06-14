from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("charging", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datasource",
            name="kind",
            field=models.CharField(default="provider", max_length=40),
        ),
        migrations.AlterField(
            model_name="datasource",
            name="is_mock",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="station",
            name="is_sample_data",
            field=models.BooleanField(default=False),
        ),
    ]
