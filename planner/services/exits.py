import json
import re
from pathlib import Path

import requests

from planner.services.osm import distance_miles

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

REQUEST_HEADERS = {
    "User-Agent": "spotter-fuel-route-assessment/1.0",
}

MAX_EXIT_CLUSTER_DISTANCE_MILES = 1.0

_STATE_EXIT_MEMORY_CACHE = {}


def extract_exit_number(address):
    if not address:
        return None

    match = re.search(
        r"\bEXIT\s+([A-Z0-9-]+)",
        address.upper(),
    )

    if not match:
        return None

    return match.group(1)


def build_state_exit_query(state_code):
    return f"""
    [out:json][timeout:90];

    rel
      ["boundary"="administrative"]
      ["admin_level"="4"]
      ["ISO3166-2"="US-{state_code}"];

    map_to_area -> .state;

    (
        node(area.state)
          ["highway"="motorway_junction"];

        way(area.state)
          ["junction:ref"];
    );

    out center tags;
    """


def request_exit_overpass(query):
    last_error = None

    for url in OVERPASS_URLS:
        try:
            print(f"Trying exit Overpass: {url}")

            response = requests.post(
                url,
                data={"data": query},
                headers=REQUEST_HEADERS,
                timeout=120,
            )

            print(f"Exit status: {response.status_code}")

            response.raise_for_status()

            return response.json()

        except requests.RequestException as exc:
            print(f"Exit request failed: {exc}")

            last_error = exc

    if last_error:
        raise last_error

    raise RuntimeError("No Overpass endpoint available " "for exit data.")


def fetch_state_exit_candidates(
    state_code,
    suppress_errors=False,
):
    state_code = state_code.upper()

    if state_code in _STATE_EXIT_MEMORY_CACHE:
        return _STATE_EXIT_MEMORY_CACHE[state_code]

    cache_path = Path("data/" f"overpass_exits_" f"{state_code.lower()}.json")

    if cache_path.exists():
        print(f"Using exit cache: {cache_path}")

        with cache_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        _STATE_EXIT_MEMORY_CACHE[state_code] = data

        return data

    query = build_state_exit_query(state_code)

    try:
        data = request_exit_overpass(query)

    except Exception:
        empty_result = {
            "elements": [],
        }

        _STATE_EXIT_MEMORY_CACHE[state_code] = empty_result

        if suppress_errors:
            return empty_result

        raise

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

    _STATE_EXIT_MEMORY_CACHE[state_code] = data

    return data


def get_exit_candidate_coordinates(element):
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

    if latitude is None or longitude is None:
        return None

    return (
        float(latitude),
        float(longitude),
    )


def get_exit_reference(element):
    tags = element.get(
        "tags",
        {},
    )

    exit_reference = tags.get("ref") or tags.get("junction:ref")

    if not exit_reference:
        return None

    return str(exit_reference).strip().upper()


def normalize_exit_reference(value):
    if not value:
        return ""

    value = str(value).upper().strip()

    value = re.sub(
        r"\s+",
        "",
        value,
    )

    return value


def find_exit_candidates(
    state_code,
    exit_number,
):
    if not exit_number:
        return []

    data = fetch_state_exit_candidates(state_code)

    expected_reference = normalize_exit_reference(exit_number)

    matches = []

    for element in data.get(
        "elements",
        [],
    ):
        reference = get_exit_reference(element)

        if not reference:
            continue

        normalized_reference = normalize_exit_reference(reference)

        if normalized_reference != expected_reference:
            continue

        coordinates = get_exit_candidate_coordinates(element)

        if not coordinates:
            continue

        latitude, longitude = coordinates

        matches.append(
            {
                "osm_type": element.get("type"),
                "osm_id": element.get("id"),
                "latitude": latitude,
                "longitude": longitude,
                "reference": reference,
                "tags": element.get(
                    "tags",
                    {},
                ),
            }
        )

    return matches


def exit_candidates_are_close(
    first,
    second,
):
    distance = distance_miles(
        first["latitude"],
        first["longitude"],
        second["latitude"],
        second["longitude"],
    )

    return distance <= MAX_EXIT_CLUSTER_DISTANCE_MILES


def cluster_exit_candidates(candidates):
    clusters = []

    for candidate in candidates:
        matching_cluster = None

        for cluster in clusters:
            if any(
                exit_candidates_are_close(
                    candidate,
                    existing,
                )
                for existing in cluster
            ):
                matching_cluster = cluster
                break

        if matching_cluster:
            matching_cluster.append(candidate)
        else:
            clusters.append([candidate])

    return clusters


def get_exit_cluster_coordinates(cluster):
    if not cluster:
        return None

    latitude = sum(item["latitude"] for item in cluster) / len(cluster)

    longitude = sum(item["longitude"] for item in cluster) / len(cluster)

    # Keep the original function contract:
    # matching.py expects:
    #
    # latitude, longitude =
    # get_exit_cluster_coordinates(cluster)

    return latitude, longitude


def clear_exit_memory_cache():
    _STATE_EXIT_MEMORY_CACHE.clear()
