import uuid

from django.conf import settings
from django.db import models


class RoutePlan(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="route_plans",
    )
    origin_label = models.CharField(max_length=160)
    destination_label = models.CharField(max_length=160)
    origin_latitude = models.DecimalField(max_digits=9, decimal_places=6)
    origin_longitude = models.DecimalField(max_digits=9, decimal_places=6)
    destination_latitude = models.DecimalField(max_digits=9, decimal_places=6)
    destination_longitude = models.DecimalField(max_digits=9, decimal_places=6)
    distance_km = models.DecimalField(max_digits=8, decimal_places=1)
    duration_min = models.PositiveIntegerField()
    energy_kwh = models.DecimalField(max_digits=8, decimal_places=1)
    arrival_battery_percent = models.DecimalField(max_digits=5, decimal_places=1)
    recommendation_station = models.ForeignKey(
        "charging.Station",
        on_delete=models.PROTECT,
        related_name="route_plan_recommendations",
    )
    recommendation_snapshot = models.JSONField()
    alternatives_snapshot = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["public_id"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.origin_label} -> {self.destination_label}"
