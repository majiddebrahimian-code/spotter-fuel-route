import json
from pathlib import Path

from math import radians, sin, cos, sqrt, atan2

import requests

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


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
    headers = {"User-Agent": "spotter-fuel-route-assessment/1.0"}

    last_error = None

    for url in OVERPASS_URLS:
        try:
            print(f"Trying Overpass: {url}")

            response = requests.post(
                url,
                data={"data": query},
                headers=headers,
                timeout=120,
            )

            print(f"Status: {response.status_code}")

            response.raise_for_status()

            return response.json()

        except requests.RequestException as exc:
            print(f"Failed: {exc}")
            last_error = exc

    raise last_error


def fetch_state_fuel_candidates(state_code):
    state_code = state_code.upper()

    cache_path = Path(f"data/overpass_{state_code.lower()}.json")

    if cache_path.exists():
        print(f"Using cache: {cache_path}")

        with cache_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)

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

    return data


def get_coordinates(element):
    if element["type"] == "node":
        return (
            element.get("lat"),
            element.get("lon"),
        )

    center = element.get("center", {})

    return (
        center.get("lat"),
        center.get("lon"),
    )


def distance_miles(lat1, lon1, lat2, lon2):
    earth_radius_miles = 3958.8

    lat1 = radians(float(lat1))
    lon1 = radians(float(lon1))
    lat2 = radians(float(lat2))
    lon2 = radians(float(lon2))

    lat_diff = lat2 - lat1
    lon_diff = lon2 - lon1

    a = sin(lat_diff / 2) ** 2 + cos(lat1) * cos(lat2) * sin(lon_diff / 2) ** 2

    c = 2 * atan2(
        sqrt(a),
        sqrt(1 - a),
    )

    return earth_radius_miles * c
