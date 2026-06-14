import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("charging", "0003_datasource_authorization_flag"),
    ]

    operations = [
        migrations.CreateModel(
            name="RoutePlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("client_id", models.CharField(db_index=True, max_length=80)),
                ("origin_label", models.CharField(max_length=160)),
                ("destination_label", models.CharField(max_length=160)),
                ("origin_latitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("origin_longitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("destination_latitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("destination_longitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("distance_km", models.DecimalField(decimal_places=1, max_digits=8)),
                ("duration_min", models.PositiveIntegerField()),
                ("energy_kwh", models.DecimalField(decimal_places=1, max_digits=8)),
                ("arrival_battery_percent", models.DecimalField(decimal_places=1, max_digits=5)),
                ("recommendation_snapshot", models.JSONField()),
                ("alternatives_snapshot", models.JSONField(blank=True, default=list)),
                ("warnings", models.JSONField(blank=True, default=list)),
                ("request_payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "recommendation_station",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="route_plan_recommendations",
                        to="charging.station",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["client_id", "-created_at"], name="routing_rou_client__3dbfe9_idx"),
                    models.Index(fields=["public_id"], name="routing_rou_public__02dde6_idx"),
                ],
            },
        ),
    ]
