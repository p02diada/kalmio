from django.db import models


class VehicleProfileSource(models.Model):
    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=40, default="provider")
    license = models.CharField(max_length=160, blank=True)
    is_authorized = models.BooleanField(default=False)
    base_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class VehicleProfile(models.Model):
    source = models.ForeignKey(VehicleProfileSource, on_delete=models.PROTECT, related_name="vehicle_profiles")
    typecode = models.CharField(max_length=160, unique=True)
    manufacturer = models.CharField(max_length=120)
    model = models.CharField(max_length=160)
    title = models.CharField(max_length=220)
    maturity = models.CharField(max_length=32, blank=True)
    drive_train = models.CharField(max_length=80, blank=True)
    start_year = models.PositiveSmallIntegerField(null=True, blank=True)
    end_year = models.PositiveSmallIntegerField(null=True, blank=True)
    battery_capacity_wh = models.PositiveIntegerField(null=True, blank=True)
    battery_chemistry = models.CharField(max_length=32, blank=True)
    battery_name = models.CharField(max_length=120, blank=True)
    reference_consumption_wh_km = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    recommended_max_speed_kmh = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    default_connectors = models.JSONField(default=list, blank=True)
    dc_connectors = models.JSONField(default=list, blank=True)
    dc_connector_powers_w = models.JSONField(default=list, blank=True)
    ac_connectors = models.JSONField(default=list, blank=True)
    has_dcfc_preconditioning = models.BooleanField(null=True, blank=True)
    has_heatpump = models.BooleanField(null=True, blank=True)
    options = models.JSONField(default=list, blank=True)
    display_hints = models.JSONField(default=dict, blank=True)
    ideal_trip = models.JSONField(default=dict, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["manufacturer", "model"]),
            models.Index(fields=["battery_capacity_wh"]),
            models.Index(fields=["reference_consumption_wh_km"]),
        ]

    def __str__(self) -> str:
        return self.title
