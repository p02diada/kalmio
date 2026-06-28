# Generated manually for the initial vehicle profile import schema.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="VehicleProfileSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("kind", models.CharField(default="provider", max_length=40)),
                ("license", models.CharField(blank=True, max_length=160)),
                ("is_authorized", models.BooleanField(default=False)),
                ("base_url", models.URLField(blank=True)),
                ("notes", models.TextField(blank=True)),
                ("imported_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="VehicleProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("typecode", models.CharField(max_length=160, unique=True)),
                ("manufacturer", models.CharField(max_length=120)),
                ("model", models.CharField(max_length=160)),
                ("title", models.CharField(max_length=220)),
                ("maturity", models.CharField(blank=True, max_length=32)),
                ("drive_train", models.CharField(blank=True, max_length=80)),
                ("start_year", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("end_year", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("battery_capacity_wh", models.PositiveIntegerField(blank=True, null=True)),
                ("battery_chemistry", models.CharField(blank=True, max_length=32)),
                ("battery_name", models.CharField(blank=True, max_length=120)),
                ("reference_consumption_wh_km", models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ("recommended_max_speed_kmh", models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ("default_connectors", models.JSONField(blank=True, default=list)),
                ("dc_connectors", models.JSONField(blank=True, default=list)),
                ("dc_connector_powers_w", models.JSONField(blank=True, default=list)),
                ("ac_connectors", models.JSONField(blank=True, default=list)),
                ("has_dcfc_preconditioning", models.BooleanField(blank=True, null=True)),
                ("has_heatpump", models.BooleanField(blank=True, null=True)),
                ("options", models.JSONField(blank=True, default=list)),
                ("display_hints", models.JSONField(blank=True, default=dict)),
                ("ideal_trip", models.JSONField(blank=True, default=dict)),
                ("raw_payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "source",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="vehicle_profiles", to="vehicles.vehicleprofilesource"),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="vehicleprofile",
            index=models.Index(fields=["manufacturer", "model"], name="vehicles_ve_manufac_dfd860_idx"),
        ),
        migrations.AddIndex(
            model_name="vehicleprofile",
            index=models.Index(fields=["battery_capacity_wh"], name="vehicles_ve_battery_531cd4_idx"),
        ),
        migrations.AddIndex(
            model_name="vehicleprofile",
            index=models.Index(fields=["reference_consumption_wh_km"], name="vehicles_ve_referen_f4d983_idx"),
        ),
    ]
