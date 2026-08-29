import time

from django.test import TestCase

from planner.services.geocoding import geocode
from planner.services.routing import get_route
from planner.services.station_data import (
    prepare_stations_for_route,
)
from planner.services.optimizer import (
    optimize_fuel_plan,
)


class RealRouteIntegrationTest(TestCase):
    databases = {"default"}

    def test_new_york_to_miami(self):
        started_at = time.perf_counter()

        start = geocode("New York, NY")
        finish = geocode("Miami, FL")

        self.assertIsNotNone(start)
        self.assertIsNotNone(finish)

        route = get_route(
            start,
            finish,
        )

        self.assertIsNotNone(route)

        route_coordinates = (
            route["geometry"]["coordinates"]
        )

        stations = prepare_stations_for_route(
            route_coordinates=route_coordinates,
            official_distance_miles=(
                route["distance_miles"]
            ),
        )

        fuel_plan = optimize_fuel_plan(
            route_distance_miles=(
                route["distance_miles"]
            ),
            stations=stations,
        )

        elapsed = (
            time.perf_counter()
            - started_at
        )

        print()
        print("=" * 50)
        print("REAL ROUTE TEST")
        print("=" * 50)

        print(
            f"Route distance: "
            f"{route['distance_miles']:.2f} miles"
        )

        print(
            f"Route duration: "
            f"{route['duration_minutes']:.2f} minutes"
        )

        print(
            f"Candidate stations: "
            f"{len(stations)}"
        )

        print(
            f"Fuel stops: "
            f"{len(fuel_plan['fuel_stops'])}"
        )

        print(
            f"Total fuel purchased: "
            f"{fuel_plan['total_fuel_purchased_gallons']} "
            f"gallons"
        )

        print(
            f"Fuel remaining: "
            f"{fuel_plan['fuel_remaining_gallons']} "
            f"gallons"
        )

        print(
            f"Total fuel cost: "
            f"${fuel_plan['total_cost']}"
        )

        print(
            f"Estimated detour: "
            f"{fuel_plan['estimated_detour_miles']:.2f} "
            f"miles"
        )

        print(
            f"Estimated total distance: "
            f"{fuel_plan['estimated_total_distance_miles']:.2f} "
            f"miles"
        )

        print(
            f"Uncertain stops: "
            f"{fuel_plan['uncertain_stops']}"
        )

        print()
        print("SELECTED FUEL STOPS")
        print("-" * 50)

        for index, stop in enumerate(
            fuel_plan["fuel_stops"],
            start=1,
        ):
            print(
                f"{index}. "
                f"{stop['name']} | "
                f"{stop['city']}, {stop['state']}"
            )

            print(
                f"   Route mile: "
                f"{stop['route_mile']:.2f}"
            )

            print(
                f"   Detour: "
                f"{stop['detour_miles']:.2f} miles"
            )

            print(
                f"   Price: "
                f"${stop['price_per_gallon']}/gal"
            )

            print(
                f"   Fuel arrival: "
                f"{stop['fuel_on_arrival_gallons']} gal"
            )

            print(
                f"   Purchased: "
                f"{stop['gallons_purchased']} gal"
            )

            print(
                f"   Fuel departure: "
                f"{stop['fuel_on_departure_gallons']} gal"
            )

            print(
                f"   Stop cost: "
                f"${stop['stop_cost']}"
            )

            print(
                f"   Geocode: "
                f"{stop['geocode_status']}"
            )

            print()

        print("TRAVEL LEGS")
        print("-" * 50)

        for index, leg in enumerate(
            fuel_plan["travel_legs"],
            start=1,
        ):
            print(
                f"{index}. "
                f"{leg['from']} -> {leg['to']} "
                f"| {leg['distance_miles']:.2f} miles "
                f"| {leg['fuel_consumed_gallons']} gal"
            )

        print()
        print(
            f"Total execution time: "
            f"{elapsed:.3f} seconds"
        )

        print("=" * 50)

        self.assertGreater(
            route["distance_miles"],
            500,
        )

        self.assertGreater(
            len(stations),
            0,
        )

        self.assertGreater(
            len(fuel_plan["fuel_stops"]),
            0,
        )

        self.assertGreater(
            fuel_plan[
                "total_fuel_purchased_gallons"
            ],
            0,
        )

        self.assertGreater(
            fuel_plan["total_cost"],
            0,
        )

        previous_route_mile = 0

        for stop in fuel_plan["fuel_stops"]:
            self.assertGreaterEqual(
                stop["route_mile"],
                previous_route_mile,
            )

            previous_route_mile = (
                stop["route_mile"]
            )

        for leg in fuel_plan["travel_legs"]:
            self.assertLessEqual(
                leg["distance_miles"],
                500,
            )