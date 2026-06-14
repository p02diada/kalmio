from django.db import models


class AuthThrottle(models.Model):
    key = models.CharField(max_length=128, unique=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    window_started_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["window_started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.key[:12]}:{self.attempts}"
