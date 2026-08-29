import requests

ROUTE_URL = "https://router.project-osrm.org/route/v1/driving"

MAX_ROUTE_CANDIDATES = 3


def _build_coordinates(start, finish):
    return f'{start["lon"]},{start["lat"]};' f'{finish["lon"]},{finish["lat"]}'


def _request_routes(start, finish, alternatives=False):
    coordinates = _build_coordinates(start, finish)

    url = f"{ROUTE_URL}/{coordinates}"

    params = {
        "overview": "full",
        "geometries": "geojson",
    }

    if alternatives:
        # Primary route + up to two alternatives.
        params["alternatives"] = MAX_ROUTE_CANDIDATES - 1

    response = requests.get(
        url,
        params=params,
        timeout=15,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("code") != "Ok":
        return []

    return data.get("routes", [])


def _serialize_route(route, route_index):
    return {
        "route_index": route_index,
        "distance_miles": route["distance"] / 1609.344,
        "duration_minutes": route["duration"] / 60,
        "geometry": route["geometry"],
    }


def get_route(start, finish):
    """
    Return the primary OSRM route.

    Kept for backward compatibility with the existing API.
    """

    routes = _request_routes(
        start,
        finish,
        alternatives=False,
    )

    if not routes:
        return None

    return _serialize_route(
        routes[0],
        route_index=0,
    )


def get_route_candidates(start, finish):
    """
    Return the primary OSRM route and available alternatives.

    Only one OSRM request is made. Each candidate route can later
    be evaluated independently by the fuel optimizer.
    """

    routes = _request_routes(
        start,
        finish,
        alternatives=True,
    )

    candidates = []

    for route_index, route in enumerate(routes[:MAX_ROUTE_CANDIDATES]):
        candidates.append(
            _serialize_route(
                route,
                route_index=route_index,
            )
        )

    return candidates
