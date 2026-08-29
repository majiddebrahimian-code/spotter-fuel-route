from collections import defaultdict
from decimal import Decimal

from django.db.models import Prefetch

from planner.models import FuelPrice, FuelStation
from planner.services.corridor import (
    build_route_index,
    expanded_route_bounds,
    project_stations_to_route,
)

USABLE_GEOCODE_STATUSES = (
    "exact",
    "approximate",
    "uncertain",
)

MAX_STATION_DETOUR_MILES = 500.0
ROUTE_SEARCH_MARGIN_MILES = 500.0

OPTIMIZER_BUCKET_MILES = 40.0
MAX_STATIONS_PER_BUCKET = 5


def _median_decimal(values):
    values = sorted(Decimal(str(value)) for value in values)

    if not values:
        return None

    middle = len(values) // 2

    if len(values) % 2:
        return values[middle]

    return (values[middle - 1] + values[middle]) / Decimal("2")


def get_station_price(station):
    if hasattr(station, "_optimizer_prices"):
        prices = [item.price for item in station._optimizer_prices]
    else:
        prices = station.prices.values_list(
            "price",
            flat=True,
        )

    return _median_decimal(prices)


def get_geocoded_stations(
    bounds=None,
    states=None,
):
    price_queryset = FuelPrice.objects.only(
        "station_id",
        "price",
    )

    queryset = (
        FuelStation.objects.filter(
            geocode_status__in=USABLE_GEOCODE_STATUSES,
            latitude__isnull=False,
            longitude__isnull=False,
        )
        .only(
            "id",
            "opis_id",
            "name",
            "address",
            "city",
            "state",
            "latitude",
            "longitude",
            "geocode_status",
            "match_score",
            "match_margin",
        )
        .prefetch_related(
            Prefetch(
                "prices",
                queryset=price_queryset,
                to_attr="_optimizer_prices",
            )
        )
        .order_by("id")
    )

    if states:
        queryset = queryset.filter(
            state__in=states,
        )

    if bounds:
        queryset = queryset.filter(
            latitude__gte=bounds["min_lat"],
            latitude__lte=bounds["max_lat"],
            longitude__gte=bounds["min_lon"],
            longitude__lte=bounds["max_lon"],
        )

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
                "latitude": station.latitude,
                "longitude": station.longitude,
                "price": price,
                "geocode_status": station.geocode_status,
                "match_score": station.match_score,
                "match_margin": station.match_margin,
                "is_uncertain": (station.geocode_status == "uncertain"),
            }
        )

    return stations


def _station_identity(station):
    return station["station_id"]


def _add_unique(
    selected,
    selected_ids,
    station,
):
    if station is None:
        return

    station_id = _station_identity(station)

    if station_id in selected_ids:
        return

    selected.append(station)
    selected_ids.add(station_id)


def _pareto_frontier(stations):
    """
    Keep useful price/detour trade-offs.

    A station is dominated when another station is both
    cheaper and no farther from the route.
    """
    ordered = sorted(
        stations,
        key=lambda station: (
            station["price"],
            station["detour_miles"],
            station["is_uncertain"],
        ),
    )

    frontier = []
    best_detour = float("inf")

    for station in ordered:
        detour = station["detour_miles"]

        if detour < best_detour:
            frontier.append(station)
            best_detour = detour

    return frontier


def _sample_frontier(
    frontier,
    maximum,
):
    if len(frontier) <= maximum:
        return frontier

    if maximum <= 1:
        return [frontier[0]]

    indexes = {
        round(index * (len(frontier) - 1) / (maximum - 1)) for index in range(maximum)
    }

    return [frontier[index] for index in sorted(indexes)]


def _select_bucket_stations(stations):
    if len(stations) <= MAX_STATIONS_PER_BUCKET:
        return stations

    selected = []
    selected_ids = set()

    cheapest = min(
        stations,
        key=lambda station: (
            station["price"],
            station["is_uncertain"],
            station["detour_miles"],
        ),
    )

    closest = min(
        stations,
        key=lambda station: (
            station["detour_miles"],
            station["price"],
            station["is_uncertain"],
        ),
    )

    trusted_stations = [station for station in stations if not station["is_uncertain"]]

    cheapest_trusted = None

    if trusted_stations:
        cheapest_trusted = min(
            trusted_stations,
            key=lambda station: (
                station["price"],
                station["detour_miles"],
            ),
        )

    _add_unique(
        selected,
        selected_ids,
        cheapest,
    )

    _add_unique(
        selected,
        selected_ids,
        closest,
    )

    _add_unique(
        selected,
        selected_ids,
        cheapest_trusted,
    )

    frontier = _pareto_frontier(stations)

    remaining_slots = MAX_STATIONS_PER_BUCKET - len(selected)

    if remaining_slots > 0:
        sampled_frontier = _sample_frontier(
            frontier,
            remaining_slots,
        )

        for station in sampled_frontier:
            _add_unique(
                selected,
                selected_ids,
                station,
            )

            if len(selected) >= MAX_STATIONS_PER_BUCKET:
                break

    if len(selected) < MAX_STATIONS_PER_BUCKET:
        remaining = sorted(
            stations,
            key=lambda station: (
                station["price"],
                station["detour_miles"],
                station["is_uncertain"],
            ),
        )

        for station in remaining:
            _add_unique(
                selected,
                selected_ids,
                station,
            )

            if len(selected) >= MAX_STATIONS_PER_BUCKET:
                break

    return selected


def select_optimizer_candidates(stations):
    """
    Reduce dense station data while preserving route coverage.

    Stations are grouped by route progress rather than by
    a hard distance-from-route corridor.
    """
    buckets = defaultdict(list)

    for station in stations:
        bucket_index = int(station["route_mile"] // OPTIMIZER_BUCKET_MILES)

        buckets[bucket_index].append(station)

    selected = []

    for bucket_index in sorted(buckets):
        bucket_stations = buckets[bucket_index]

        selected.extend(_select_bucket_stations(bucket_stations))

    selected.sort(
        key=lambda station: (
            station["route_mile"],
            station["detour_miles"],
        )
    )

    return selected


def prepare_stations_for_route(
    route_coordinates,
    official_distance_miles,
    states=None,
):
    route_index = build_route_index(
        route_coordinates,
        official_distance_miles=(official_distance_miles),
    )

    bounds = expanded_route_bounds(
        route_index,
        margin_miles=(ROUTE_SEARCH_MARGIN_MILES),
    )

    stations = get_geocoded_stations(
        bounds=bounds,
        states=states,
    )

    projected_stations = project_stations_to_route(
        stations,
        route_index,
        max_detour_miles=(MAX_STATION_DETOUR_MILES),
    )

    return select_optimizer_candidates(projected_stations)
