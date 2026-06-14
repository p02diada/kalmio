from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

from django.db.models import Count, Max, Prefetch, QuerySet

from charging.models import AvailabilitySnapshot, Connector, Station


@dataclass(frozen=True)
class NearbyStation:
    station: Station
    distance_km: float
    max_power_kw: int
    connector_types: list[str]
    available_evses: int


def stations_queryset() -> QuerySet[Station]:
    return (
        Station.objects.select_related("operator", "data_source", "reliability")
        .filter(is_sample_data=False, data_source__is_authorized=True)
        .prefetch_related(
            Prefetch("evses__connectors", queryset=Connector.objects.order_by("connector_type", "-max_power_kw")),
            Prefetch("evses__availability_snapshots", queryset=AvailabilitySnapshot.objects.order_by("-observed_at")),
            "tariffs",
        )
        .annotate(max_power_kw=Max("evses__max_power_kw"), evse_count=Count("evses", distinct=True))
        .order_by("name")
    )


def get_nearby_stations(
    lat: float,
    lon: float,
    radius_km: float = 80,
    connector: str | None = None,
    min_power_kw: int | None = None,
    available_only: bool = False,
) -> list[NearbyStation]:
    queryset = stations_queryset()

    if connector:
        queryset = queryset.filter(evses__connectors__connector_type__iexact=connector)

    if min_power_kw:
        queryset = queryset.filter(evses__max_power_kw__gte=min_power_kw)

    if available_only:
        queryset = queryset.filter(evses__status="available")

    results: list[NearbyStation] = []
    seen: set[int] = set()
    for station in queryset:
        if station.id in seen:
            continue
        seen.add(station.id)
        distance = haversine_km(lat, lon, float(station.latitude), float(station.longitude))
        if distance <= radius_km:
            connectors = sorted(
                {
                    connector.connector_type
                    for evse in station.evses.all()
                    for connector in evse.connectors.all()
                }
            )
            results.append(
                NearbyStation(
                    station=station,
                    distance_km=round(distance, 2),
                    max_power_kw=max((evse.max_power_kw for evse in station.evses.all()), default=0),
                    connector_types=connectors,
                    available_evses=sum(1 for evse in station.evses.all() if evse.status == "available"),
                )
            )

    return sorted(results, key=lambda item: item.distance_km)


def haversine_km(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float) -> float:
    radius = 6371.0
    dlat = radians(dest_lat - origin_lat)
    dlon = radians(dest_lon - origin_lon)
    lat1 = radians(origin_lat)
    lat2 = radians(dest_lat)

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * radius * asin(sqrt(a))
