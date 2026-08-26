import requests

ROUTE_URL = "https://router.project-osrm.org/route/v1/driving"


def get_route(start, finish):
    coordinates = f'{start["lon"]},{start["lat"]};' f'{finish["lon"]},{finish["lat"]}'

    url = f"{ROUTE_URL}/{coordinates}"

    params = {
        "overview": "full",
        "geometries": "geojson",
    }

    response = requests.get(
        url,
        params=params,
        timeout=15,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        return None

    route = data["routes"][0]

    return {
        "distance_miles": route["distance"] / 1609.344,
        "duration_minutes": route["duration"] / 60,
        "geometry": route["geometry"],
    }
