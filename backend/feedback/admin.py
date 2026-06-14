from django.contrib import admin

from feedback.models import Feedback


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("kind", "user", "route_plan", "created_at")
    list_filter = ("kind", "created_at")
    search_fields = ("user__username", "user__email", "route_plan__public_id", "comment")
    readonly_fields = ("created_at",)
