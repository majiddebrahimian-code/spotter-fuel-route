import re

from planner.services.geocoding import geocode
from planner.services.osm import distance_miles


def has_highway_intersection(address):
    if not address:
        return False

    address = address.upper()

    has_separator = "&" in address or "/" in address

    has_highway = any(
        marker in address
        for marker in [
            "I-",
            "US-",
            "SR-",
            "SH-",
            "HWY",
            "HIGHWAY",
        ]
    )

    return has_separator and has_highway


def normalize_highway_address(address):
    if not address:
        return ""

    value = address.upper()

    value = re.sub(
        r",?\s*EXIT\s+[A-Z0-9-]+",
        "",
        value,
    )

    value = value.replace(
        "SR-",
        "STATE HIGHWAY ",
    )

    value = value.replace(
        "SH-",
        "STATE HIGHWAY ",
    )

    value = value.replace(
        "US-",
        "US ",
    )

    value = value.replace(
        "I-",
        "INTERSTATE ",
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip(" ,")


def build_intersection_queries(
    station_name,
    address,
    city,
    state,
):
    normalized_address = normalize_highway_address(address)

    queries = []

    if normalized_address:
        queries.append(f"{normalized_address}, " f"{city}, {state}, USA")

    if "/" in address:
        parts = address.split("&")

        if len(parts) >= 2:
            left_side = parts[0].strip()
            right_side = parts[1].strip()

            left_routes = [
                route.strip() for route in left_side.split("/") if route.strip()
            ]

            for route in left_routes:
                route_address = f"{route} & " f"{right_side}"

                normalized_route = normalize_highway_address(route_address)

                queries.append(f"{normalized_route}, " f"{city}, {state}, USA")

    queries.append(f"{station_name}, " f"{city}, {state}, USA")

    unique_queries = []

    for query in queries:
        if query not in unique_queries:
            unique_queries.append(query)

    return unique_queries


def find_intersection_location(
    station_name,
    address,
    city,
    state,
):
    queries = build_intersection_queries(
        station_name,
        address,
        city,
        state,
    )

    city_location = geocode(f"{city}, {state}")

    if not city_location:
        return None

    results = []

    for query in queries:
        location = geocode(query)

        if not location:
            continue

        city_distance = distance_miles(
            city_location["lat"],
            city_location["lon"],
            location["lat"],
            location["lon"],
        )

        results.append(
            {
                "query": query,
                "latitude": location["lat"],
                "longitude": location["lon"],
                "name": location["name"],
                "city_distance_miles": city_distance,
            }
        )

    if not results:
        return None

    nearby_results = [
        result for result in results if result["city_distance_miles"] <= 15
    ]

    if nearby_results:
        results = nearby_results

    results.sort(key=lambda result: (result["city_distance_miles"]))

    return {
        "best": results[0],
        "results": results,
    }
