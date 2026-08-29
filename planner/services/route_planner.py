from planner.services.geocoding import geocode
from planner.services.optimizer import optimize_fuel_plan
from planner.services.routing import get_route
from planner.services.station_data import prepare_stations_for_route


class LocationNotFoundError(Exception):
    pass


class RouteUnavailableError(Exception):
    pass


def plan_route(start_location, finish_location):
    start = geocode(start_location)

    if not start:
        raise LocationNotFoundError("Start location could not be found in the USA.")

    finish = geocode(finish_location)

    if not finish:
        raise LocationNotFoundError("Finish location could not be found in the USA.")

    route = get_route(
        start,
        finish,
    )

    if not route:
        raise RouteUnavailableError("Routing service is temporarily unavailable.")

    stations = prepare_stations_for_route(
        route_coordinates=route["geometry"]["coordinates"],
        official_distance_miles=route["distance_miles"],
    )

    fuel_plan = optimize_fuel_plan(
        route_distance_miles=route["distance_miles"],
        stations=stations,
    )

    return {
        "start": {
            "name": start["name"],
            "lat": start["lat"],
            "lon": start["lon"],
        },
        "finish": {
            "name": finish["name"],
            "lat": finish["lat"],
            "lon": finish["lon"],
        },
        "route": {
            "distance_miles": round(
                route["distance_miles"],
                2,
            ),
            "duration_minutes": round(
                route["duration_minutes"],
                2,
            ),
            "geometry": route["geometry"],
        },
        "vehicle": {
            "mpg": 10,
            "max_range_miles": 500,
            "tank_capacity_gallons": 50,
            "initial_fuel_gallons": 50,
        },
        "fuel_plan": fuel_plan,
    }
