from django.contrib import admin

from routing.models import RoutePlan


@admin.register(RoutePlan)
class RoutePlanAdmin(admin.ModelAdmin):
    list_display = ("public_id", "user", "origin_label", "destination_label", "created_at")
    list_filter = ("created_at",)
    search_fields = ("public_id", "user__username", "user__email", "origin_label", "destination_label")
    readonly_fields = ("public_id", "created_at")
