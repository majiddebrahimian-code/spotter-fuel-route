import json
import re
from pathlib import Path

from planner.services.osm import (
    OVERPASS_URLS,
    distance_miles,
)

import requests

MAX_EXIT_CLUSTER_DISTANCE_MILES = 1.0


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


def normalize_exit_ref(value):
    if not value:
        return ""

    return str(value).upper().replace("EXIT", "").replace(" ", "").strip()


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


def fetch_state_exits(state_code):
    state_code = state_code.upper()

    cache_path = Path(f"data/overpass_exits_{state_code.lower()}.json")

    if cache_path.exists():
        print(f"Using exit cache: {cache_path}")

        with cache_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)

    query = build_state_exit_query(state_code)

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


def get_exit_coordinates(element):
    if element["type"] == "node":
        return (
            element.get("lat"),
            element.get("lon"),
        )

    center = element.get(
        "center",
        {},
    )

    return (
        center.get("lat"),
        center.get("lon"),
    )


def find_exit_candidates(
    state_code,
    exit_number,
):
    data = fetch_state_exits(state_code)

    wanted_exit = normalize_exit_ref(exit_number)

    results = []

    for element in data.get(
        "elements",
        [],
    ):
        tags = element.get(
            "tags",
            {},
        )

        references = [
            tags.get("ref"),
            tags.get("junction:ref"),
            tags.get("ref:left"),
            tags.get("ref:right"),
        ]

        matched = False

        for reference in references:
            if normalize_exit_ref(reference) == wanted_exit:
                matched = True
                break

        if not matched:
            continue

        latitude, longitude = get_exit_coordinates(element)

        if latitude is None or longitude is None:
            continue

        results.append(
            {
                "osm_id": element.get("id"),
                "osm_type": element.get("type"),
                "latitude": latitude,
                "longitude": longitude,
                "tags": tags,
            }
        )

    return results


def cluster_exit_candidates(
    exit_candidates,
):
    groups = []

    for candidate in exit_candidates:
        matched_group = None

        for group in groups:
            for member in group:
                distance = distance_miles(
                    candidate["latitude"],
                    candidate["longitude"],
                    member["latitude"],
                    member["longitude"],
                )

                if distance <= MAX_EXIT_CLUSTER_DISTANCE_MILES:
                    matched_group = group
                    break

            if matched_group:
                break

        if matched_group:
            matched_group.append(candidate)
        else:
            groups.append([candidate])

    return groups


def get_exit_cluster_coordinates(
    group,
):
    latitude = sum(float(candidate["latitude"]) for candidate in group) / len(group)

    longitude = sum(float(candidate["longitude"]) for candidate in group) / len(group)

    return (
        latitude,
        longitude,
    )
