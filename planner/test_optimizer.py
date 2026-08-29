from decimal import Decimal

from django.test import SimpleTestCase

from planner.services.optimizer import (
    NoFeasibleFuelPlan,
    optimize_fuel_plan,
)


def make_station(
    name,
    route_mile,
    price,
    *,
    detour_miles=0,
    geocode_status="exact",
    station_id=1,
):
    return {
        "station_id": station_id,
        "opis_id": station_id,
        "name": name,
        "address": f"{name} address",
        "city": "Test City",
        "state": "TX",
        "latitude": Decimal("32.000000"),
        "longitude": Decimal("-97.000000"),
        "price": Decimal(str(price)),
        "route_mile": route_mile,
        "detour_miles": detour_miles,
        "geocode_status": geocode_status,
        "match_score": Decimal("90"),
        "match_margin": Decimal("20"),
    }


class FuelOptimizerTests(SimpleTestCase):

    def test_route_under_500_miles_needs_no_stop(self):
        result = optimize_fuel_plan(
            route_distance_miles=300,
            stations=[],
        )

        self.assertEqual(
            result["total_cost"],
            Decimal("0"),
        )

        self.assertEqual(
            result["fuel_stops"],
            [],
        )

        self.assertEqual(
            result["fuel_remaining_gallons"],
            Decimal("20.0"),
        )

    def test_exactly_500_miles_is_reachable(self):
        result = optimize_fuel_plan(
            route_distance_miles=500,
            stations=[],
        )

        self.assertEqual(
            result["total_cost"],
            Decimal("0"),
        )

        self.assertEqual(
            result["fuel_remaining_gallons"],
            Decimal("0.0"),
        )

        self.assertEqual(
            len(result["fuel_stops"]),
            0,
        )

    def test_route_over_500_miles_requires_fuel(self):
        station = make_station(
            "Pilot",
            route_mile=400,
            price="3.00",
        )

        result = optimize_fuel_plan(
            route_distance_miles=600,
            stations=[station],
        )

        self.assertEqual(
            len(result["fuel_stops"]),
            1,
        )

        stop = result["fuel_stops"][0]

        self.assertEqual(
            stop["name"],
            "Pilot",
        )

        self.assertEqual(
            stop["gallons_purchased"],
            Decimal("10.0"),
        )

        self.assertEqual(
            result["total_cost"],
            Decimal("30"),
        )

    def test_impossible_gap_raises_error(self):
        station = make_station(
            "Too Far",
            route_mile=600,
            price="2.00",
        )

        with self.assertRaises(NoFeasibleFuelPlan):
            optimize_fuel_plan(
                route_distance_miles=1000,
                stations=[station],
            )

    def test_expensive_station_buys_only_needed_fuel(self):
        expensive = make_station(
            "Expensive",
            route_mile=400,
            price="4.00",
            station_id=1,
        )

        cheap = make_station(
            "Cheap",
            route_mile=750,
            price="2.00",
            station_id=2,
        )

        result = optimize_fuel_plan(
            route_distance_miles=1000,
            stations=[
                expensive,
                cheap,
            ],
        )

        first_stop = result["fuel_stops"][0]

        self.assertEqual(
            first_stop["name"],
            "Expensive",
        )

        self.assertEqual(
            first_stop["gallons_purchased"],
            Decimal("25.0"),
        )

        self.assertEqual(
            result["total_cost"],
            Decimal("150"),
        )

    def test_cheap_station_buys_extra_before_expensive_station(self):
        cheap = make_station(
            "Cheap",
            route_mile=400,
            price="2.00",
            station_id=1,
        )

        expensive = make_station(
            "Expensive",
            route_mile=750,
            price="4.00",
            station_id=2,
        )

        result = optimize_fuel_plan(
            route_distance_miles=1000,
            stations=[
                cheap,
                expensive,
            ],
        )

        first_stop = result["fuel_stops"][0]

        second_stop = result["fuel_stops"][1]

        self.assertEqual(
            first_stop["name"],
            "Cheap",
        )

        self.assertEqual(
            first_stop["gallons_purchased"],
            Decimal("40.0"),
        )

        self.assertEqual(
            first_stop["fuel_on_departure_gallons"],
            Decimal("50.0"),
        )

        self.assertEqual(
            second_stop["gallons_purchased"],
            Decimal("10.0"),
        )

        self.assertEqual(
            result["total_cost"],
            Decimal("120"),
        )

    def test_uncertain_station_can_win_when_cheaper(self):
        uncertain = make_station(
            "Uncertain",
            route_mile=400.2,
            detour_miles=0.1,
            price="2.90",
            geocode_status="uncertain",
            station_id=1,
        )

        trusted = make_station(
            "Trusted",
            route_mile=400.2,
            detour_miles=0.2,
            price="3.00",
            geocode_status="exact",
            station_id=2,
        )

        result = optimize_fuel_plan(
            route_distance_miles=600,
            stations=[
                uncertain,
                trusted,
            ],
        )

        self.assertEqual(
            result["fuel_stops"][0]["name"],
            "Uncertain",
        )

        self.assertEqual(
            result["uncertain_stops"],
            1,
        )

    def test_trusted_wins_equal_cost_even_with_larger_detour(self):
        uncertain = make_station(
            "Uncertain",
            route_mile=400.2,
            detour_miles=0.1,
            price="3.00",
            geocode_status="uncertain",
            station_id=1,
        )

        trusted = make_station(
            "Trusted",
            route_mile=400.2,
            detour_miles=0.2,
            price="3.00",
            geocode_status="exact",
            station_id=2,
        )

        result = optimize_fuel_plan(
            route_distance_miles=600,
            stations=[
                uncertain,
                trusted,
            ],
        )

        self.assertEqual(
            result["total_cost"],
            Decimal("30.3"),
        )

        self.assertEqual(
            result["fuel_stops"][0]["name"],
            "Trusted",
        )

        self.assertEqual(
            result["uncertain_stops"],
            0,
        )

    def test_station_more_than_five_miles_off_route_can_be_used(self):
        station = make_station(
            "Far But Useful",
            route_mile=400,
            detour_miles=12,
            price="3.00",
        )

        result = optimize_fuel_plan(
            route_distance_miles=700,
            stations=[station],
        )

        self.assertEqual(
            result["fuel_stops"][0]["name"],
            "Far But Useful",
        )

        self.assertEqual(
            result["estimated_detour_miles"],
            24.0,
        )

        self.assertEqual(
            result["fuel_stops"][0]["gallons_purchased"],
            Decimal("22.4"),
        )

    def test_detour_can_make_station_unreachable(self):
        station = make_station(
            "Unreachable",
            route_mile=490,
            detour_miles=20,
            price="1.00",
        )

        with self.assertRaises(NoFeasibleFuelPlan):
            optimize_fuel_plan(
                route_distance_miles=900,
                stations=[station],
            )

    def test_zero_purchase_station_is_skipped(self):
        useless = make_station(
            "Useless",
            route_mile=100,
            price="100.00",
            station_id=1,
        )

        useful = make_station(
            "Useful",
            route_mile=400,
            price="1.00",
            station_id=2,
        )

        result = optimize_fuel_plan(
            route_distance_miles=600,
            stations=[
                useless,
                useful,
            ],
        )

        stop_names = [stop["name"] for stop in result["fuel_stops"]]

        self.assertNotIn(
            "Useless",
            stop_names,
        )

        self.assertEqual(
            stop_names,
            ["Useful"],
        )

    def test_fractional_price_is_calculated_exactly(self):
        station = make_station(
            "Precise Price",
            route_mile=400,
            price="3.007333",
        )

        result = optimize_fuel_plan(
            route_distance_miles=600,
            stations=[station],
        )

        self.assertEqual(
            result["total_cost"],
            Decimal("30.07333"),
        )

    def test_fuel_consumption_rounds_up(self):
        station = make_station(
            "Fractional Distance",
            route_mile=400.05,
            price="3.00",
        )

        result = optimize_fuel_plan(
            route_distance_miles=600,
            stations=[station],
        )

        stop = result["fuel_stops"][0]

        self.assertEqual(
            stop["fuel_on_arrival_gallons"],
            Decimal("9.9"),
        )

        self.assertEqual(
            stop["gallons_purchased"],
            Decimal("10.1"),
        )

    def test_destination_never_appears_as_fuel_stop(self):
        station = make_station(
            "Pilot",
            route_mile=400,
            price="3.00",
        )

        result = optimize_fuel_plan(
            route_distance_miles=600,
            stations=[station],
        )

        names = [stop["name"] for stop in result["fuel_stops"]]

        self.assertNotIn(
            "destination",
            names,
        )

    def test_all_travel_legs_respect_vehicle_range(self):
        stations = [
            make_station(
                "Station A",
                route_mile=400,
                price="3.00",
                station_id=1,
            ),
            make_station(
                "Station B",
                route_mile=750,
                price="2.50",
                station_id=2,
            ),
            make_station(
                "Station C",
                route_mile=1100,
                price="2.80",
                station_id=3,
            ),
        ]

        result = optimize_fuel_plan(
            route_distance_miles=1400,
            stations=stations,
        )

        for leg in result["travel_legs"]:
            self.assertLessEqual(
                leg["distance_miles"],
                500,
            )

    def test_selected_stations_are_in_forward_order(self):
        stations = [
            make_station(
                "A",
                route_mile=350,
                price="3.50",
                station_id=1,
            ),
            make_station(
                "B",
                route_mile=700,
                price="2.50",
                station_id=2,
            ),
            make_station(
                "C",
                route_mile=1050,
                price="3.00",
                station_id=3,
            ),
        ]

        result = optimize_fuel_plan(
            route_distance_miles=1300,
            stations=stations,
        )

        route_miles = [stop["route_mile"] for stop in result["fuel_stops"]]

        self.assertEqual(
            route_miles,
            sorted(route_miles),
        )
