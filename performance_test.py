import os
import time

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()

from planner.services.geocoding import geocode
from planner.services.routing import get_route
from planner.services.station_data import prepare_stations_for_route
from planner.services.optimizer import optimize_fuel_plan


def measure(label, function):
    started = time.perf_counter()

    result = function()

    elapsed = time.perf_counter() - started

    print(f"{label}: {elapsed:.3f} seconds")

    return result, elapsed


print("=" * 60)
print("PERFORMANCE TEST — NEW YORK TO MIAMI")
print("=" * 60)


# 1. Geocoding
start, start_time = measure(
    "Start geocoding",
    lambda: geocode("New York, NY"),
)

finish, finish_time = measure(
    "Finish geocoding",
    lambda: geocode("Miami, FL"),
)


# 2. Routing
route, routing_time = measure(
    "OSRM routing",
    lambda: get_route(start, finish),
)

print(f"Route distance: " f"{route['distance_miles']:.2f} miles")


# 3. Station preparation
stations, station_time = measure(
    "Station preparation",
    lambda: prepare_stations_for_route(
        route_coordinates=route["geometry"]["coordinates"],
        official_distance_miles=route["distance_miles"],
    ),
)

print(f"Candidate stations: {len(stations)}")


# 4. Fuel optimization
fuel_plan, optimizer_time = measure(
    "Fuel optimizer",
    lambda: optimize_fuel_plan(
        route_distance_miles=route["distance_miles"],
        stations=stations,
    ),
)


total_time = start_time + finish_time + routing_time + station_time + optimizer_time


print()
print("=" * 60)
print("RESULT")
print("=" * 60)

print(f"Fuel stops: " f"{len(fuel_plan['fuel_stops'])}")

print(f"Total cost: " f"${fuel_plan['total_cost']}")

print()
print("TIMING")
print("-" * 60)

print(f"Geocoding total: " f"{start_time + finish_time:.3f}s")

print(f"OSRM routing: " f"{routing_time:.3f}s")

print(f"Station preparation: " f"{station_time:.3f}s")

print(f"Fuel optimizer: " f"{optimizer_time:.3f}s")

print("-" * 60)

print(f"TOTAL: " f"{total_time:.3f}s")

print("=" * 60)
