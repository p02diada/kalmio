from django.shortcuts import get_object_or_404
from ninja import Router, Query

from charging.models import Station
from charging.schemas import StationDetail, StationSummary
from charging.selectors import get_nearby_stations, stations_queryset

router = Router(tags=["charging"])


@router.get("/stations/nearby", response=list[StationSummary])
def stations_nearby(
    request,
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(80),
    connector: str | None = Query(None),
    min_power_kw: int | None = Query(None),
    available_only: bool = Query(False),
):
    nearby = get_nearby_stations(
        lat=lat,
        lon=lon,
        radius_km=radius_km,
        connector=connector,
        min_power_kw=min_power_kw,
        available_only=available_only,
    )
    return [station_summary(item.station, item.distance_km, item.max_power_kw, item.connector_types, item.available_evses) for item in nearby]


@router.get("/stations/{station_id}", response=StationDetail)
def station_detail(request, station_id: int):
    station = get_object_or_404(stations_queryset(), pk=station_id)
    summary = station_summary(
        station=station,
        distance_km=None,
        max_power_kw=max((evse.max_power_kw for evse in station.evses.all()), default=0),
        connector_types=sorted({connector.connector_type for evse in station.evses.all() for connector in evse.connectors.all()}),
        available_evses=sum(1 for evse in station.evses.all() if evse.status == "available"),
    )
    return {
        **summary,
        "address": station.address,
        "evses": [
            {
                "uid": evse.evse_uid,
                "status": evse.status,
                "max_power_kw": evse.max_power_kw,
                "connectors": [
                    {"type": connector.connector_type, "max_power_kw": connector.max_power_kw}
                    for connector in evse.connectors.all()
                ],
            }
            for evse in station.evses.all()
        ],
        "warnings": [],
    }


def station_summary(
    station: Station,
    distance_km: float | None,
    max_power_kw: int,
    connector_types: list[str],
    available_evses: int,
) -> dict:
    tariff = station.tariffs.first()
    return {
        "id": station.id,
        "external_id": station.external_id,
        "name": station.name,
        "operator": station.operator.name,
        "latitude": float(station.latitude),
        "longitude": float(station.longitude),
        "distance_km": distance_km,
        "max_power_kw": max_power_kw,
        "connector_types": connector_types,
        "available_evses": available_evses,
        "price_per_kwh": float(tariff.price_per_kwh) if tariff else None,
        "currency": tariff.currency if tariff else "EUR",
        "amenities": station.amenities,
        "reliability_score": station.reliability.score if hasattr(station, "reliability") else None,
    }
