from django.conf import settings
from django.db import models


class Feedback(models.Model):
    KIND_CHOICES = [
        ("useful", "Useful"),
        ("not_useful", "Not useful"),
        ("charger_busy", "Charger busy"),
        ("wrong_data", "Wrong data"),
        ("wrong_price", "Wrong price"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="feedback")
    route_plan = models.ForeignKey("routing.RoutePlan", on_delete=models.CASCADE, related_name="feedback")
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.kind} feedback"
