from django.contrib import admin

from charging.models import (
    AvailabilitySnapshot,
    Connector,
    DataSource,
    EVSE,
    Operator,
    ReliabilityScore,
    Station,
    Tariff,
)


class ConnectorInline(admin.TabularInline):
    model = Connector
    extra = 0


@admin.register(EVSE)
class EVSEAdmin(admin.ModelAdmin):
    list_display = ("evse_uid", "station", "max_power_kw", "status")
    list_filter = ("status", "max_power_kw")
    search_fields = ("evse_uid", "station__name")
    inlines = [ConnectorInline]


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ("name", "operator", "latitude", "longitude", "is_sample_data")
    list_filter = ("is_sample_data", "operator")
    search_fields = ("name", "external_id", "address")


admin.site.register(Operator)
admin.site.register(DataSource)
admin.site.register(Tariff)
admin.site.register(AvailabilitySnapshot)
admin.site.register(ReliabilityScore)
