import json
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path

import requests

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

REQUEST_HEADERS = {
    "User-Agent": "spotter-fuel-route-assessment/1.0",
}

_STATE_FUEL_MEMORY_CACHE = {}


def build_state_query(state_code):
    return f"""
    [out:json][timeout:90];

    rel
      ["boundary"="administrative"]
      ["admin_level"="4"]
      ["ISO3166-2"="US-{state_code}"];

    map_to_area -> .state;

    (
        nwr(area.state)["amenity"="fuel"];
        nwr(area.state)["highway"="services"];
    );

    out center tags;
    """


def request_overpass(query):
    last_error = None

    for url in OVERPASS_URLS:
        try:
            print(f"Trying Overpass: {url}")

            response = requests.post(
                url,
                data={"data": query},
                headers=REQUEST_HEADERS,
                timeout=120,
            )

            print(f"Status: {response.status_code}")

            response.raise_for_status()

            return response.json()

        except requests.RequestException as exc:
            print(f"Failed: {exc}")
            last_error = exc

    if last_error:
        raise last_error

    raise RuntimeError("No Overpass endpoint available.")


def fetch_state_fuel_candidates(
    state_code,
):
    state_code = state_code.upper()

    # First level:
    # reuse already loaded state data
    # during this Python process.
    if state_code in _STATE_FUEL_MEMORY_CACHE:
        return _STATE_FUEL_MEMORY_CACHE[state_code]

    cache_path = Path(f"data/overpass_{state_code.lower()}.json")

    # Second level:
    # persistent disk cache.
    if cache_path.exists():
        print(f"Using cache: {cache_path}")

        with cache_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        _STATE_FUEL_MEMORY_CACHE[state_code] = data

        return data

    # Third level:
    # only now call Overpass.
    query = build_state_query(state_code)

    data = request_overpass(query)

    cache_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with cache_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    _STATE_FUEL_MEMORY_CACHE[state_code] = data

    return data


def clear_state_memory_cache():
    _STATE_FUEL_MEMORY_CACHE.clear()


def get_coordinates(element):
    if element.get("type") == "node":
        latitude = element.get("lat")
        longitude = element.get("lon")

    else:
        center = element.get(
            "center",
            {},
        )

        latitude = center.get("lat")
        longitude = center.get("lon")

    return latitude, longitude


def distance_miles(
    lat1,
    lon1,
    lat2,
    lon2,
):
    earth_radius_miles = 3958.8

    lat1 = radians(float(lat1))
    lon1 = radians(float(lon1))

    lat2 = radians(float(lat2))
    lon2 = radians(float(lon2))

    latitude_difference = lat2 - lat1

    longitude_difference = lon2 - lon1

    a = (
        sin(latitude_difference / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(longitude_difference / 2) ** 2
    )

    c = 2 * atan2(
        sqrt(a),
        sqrt(1 - a),
    )

    return earth_radius_miles * c
