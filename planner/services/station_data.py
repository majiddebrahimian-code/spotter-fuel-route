from decimal import Decimal
from statistics import median

from planner.models import FuelStation
from planner.services.corridor import (
    filter_stations_near_route,
)


def get_station_price(station):
    prices = list(
        station.prices.values_list(
            "price",
            flat=True,
        )
    )

    if not prices:
        return None

    return Decimal(str(median(prices)))


def get_geocoded_stations(
    states=None,
):
    queryset = FuelStation.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
    ).prefetch_related("prices")

    if states:
        queryset = queryset.filter(state__in=states)

    stations = []

    for station in queryset:
        price = get_station_price(station)

        if price is None:
            continue

        stations.append(
            {
                "station_id": station.id,
                "opis_id": station.opis_id,
                "name": station.name,
                "address": station.address,
                "city": station.city,
                "state": station.state,
                "latitude": float(station.latitude),
                "longitude": float(station.longitude),
                "price": float(price),
            }
        )

    return stations


def prepare_stations_for_route(
    route_coordinates,
    states=None,
    max_distance=5.0,
):
    stations = get_geocoded_stations(states=states)

    nearby_stations = filter_stations_near_route(
        stations,
        route_coordinates,
        max_distance=max_distance,
    )

    prepared = []

    for station in nearby_stations:
        prepared.append(
            {
                "station_id": (station["station_id"]),
                "opis_id": (station["opis_id"]),
                "name": station["name"],
                "address": station["address"],
                "city": station["city"],
                "state": station["state"],
                "latitude": (station["latitude"]),
                "longitude": (station["longitude"]),
                "price": station["price"],
                "route_mile": round(
                    station["route_mile"],
                    2,
                ),
                "detour_miles": round(
                    station["distance_from_route_miles"],
                    2,
                ),
            }
        )

    return prepared
