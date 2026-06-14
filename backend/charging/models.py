from django.db import models


class DataSource(models.Model):
    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=40, default="provider")
    license = models.CharField(max_length=120, blank=True)
    is_authorized = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class Operator(models.Model):
    name = models.CharField(max_length=120, unique=True)
    website = models.URLField(blank=True)
    support_phone = models.CharField(max_length=40, blank=True)

    def __str__(self) -> str:
        return self.name


class Station(models.Model):
    external_id = models.CharField(max_length=80, unique=True)
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT, related_name="stations")
    data_source = models.ForeignKey(DataSource, on_delete=models.PROTECT, related_name="stations")
    name = models.CharField(max_length=160)
    address = models.CharField(max_length=240, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    amenities = models.JSONField(default=list, blank=True)
    is_sample_data = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["latitude", "longitude"]),
            models.Index(fields=["is_sample_data"]),
        ]

    def __str__(self) -> str:
        return self.name


class EVSE(models.Model):
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name="evses")
    evse_uid = models.CharField(max_length=120, unique=True)
    max_power_kw = models.PositiveIntegerField()
    status = models.CharField(max_length=32, default="unknown")

    def __str__(self) -> str:
        return self.evse_uid


class Connector(models.Model):
    evse = models.ForeignKey(EVSE, on_delete=models.CASCADE, related_name="connectors")
    connector_type = models.CharField(max_length=32)
    max_power_kw = models.PositiveIntegerField()

    class Meta:
        indexes = [models.Index(fields=["connector_type", "max_power_kw"])]

    def __str__(self) -> str:
        return f"{self.connector_type} {self.max_power_kw}kW"


class Tariff(models.Model):
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name="tariffs")
    price_per_kwh = models.DecimalField(max_digits=6, decimal_places=3)
    session_fee = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="EUR")
    is_estimated = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.price_per_kwh} {self.currency}/kWh"


class AvailabilitySnapshot(models.Model):
    evse = models.ForeignKey(EVSE, on_delete=models.CASCADE, related_name="availability_snapshots")
    status = models.CharField(max_length=32)
    observed_at = models.DateTimeField()
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT, related_name="availability_snapshots")

    class Meta:
        indexes = [models.Index(fields=["observed_at", "status"])]


class ReliabilityScore(models.Model):
    station = models.OneToOneField(Station, on_delete=models.CASCADE, related_name="reliability")
    score = models.PositiveSmallIntegerField(default=70)
    reasons = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.station}: {self.score}"
