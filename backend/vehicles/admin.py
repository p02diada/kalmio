from django.contrib import admin

from vehicles.models import VehicleProfile, VehicleProfileSource


@admin.register(VehicleProfileSource)
class VehicleProfileSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "is_authorized", "imported_at")
    search_fields = ("name", "kind")


@admin.register(VehicleProfile)
class VehicleProfileAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "manufacturer",
        "model",
        "battery_capacity_wh",
        "reference_consumption_wh_km",
        "maturity",
    )
    list_filter = ("manufacturer", "maturity", "battery_chemistry")
    search_fields = ("typecode", "title", "manufacturer", "model")
