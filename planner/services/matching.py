import re

from planner.geocoding import name_similarity
from planner.services.exits import (
    cluster_exit_candidates,
    extract_exit_number,
    find_exit_candidates,
    get_exit_cluster_coordinates,
)
from planner.services.geocoding import geocode
from planner.services.intersections import (
    find_intersection_location,
    has_highway_intersection,
)
from planner.services.osm import (
    distance_miles,
    fetch_state_fuel_candidates,
    get_coordinates,
)

MAX_DUPLICATE_DISTANCE_MILES = 0.25


GENERIC_NAME_WORDS = {
    "TRAVEL",
    "CENTER",
    "CENTERS",
    "STOP",
    "STOPPING",
    "EXPRESS",
    "GAS",
    "STATION",
    "STORE",
    "STORES",
    "TRUCK",
    "TRUCKSTOP",
}


def get_candidate_names(tags):
    return [
        value
        for value in [
            tags.get("name"),
            tags.get("brand"),
            tags.get("operator"),
        ]
        if value
    ]


def get_meaningful_tokens(name):
    if not name:
        return set()

    cleaned_name = re.sub(
        r"#\s*\d+",
        " ",
        name.upper(),
    )

    cleaned_name = re.sub(
        r"[^A-Z0-9]+",
        " ",
        cleaned_name,
    )

    tokens = set(cleaned_name.split())

    return {
        token
        for token in tokens
        if (token not in GENERIC_NAME_WORDS and not token.isdigit())
    }


def get_token_similarity(
    station_name,
    candidate_name,
):
    station_tokens = get_meaningful_tokens(station_name)

    candidate_tokens = get_meaningful_tokens(candidate_name)

    if not station_tokens or not candidate_tokens:
        return 0

    common_tokens = station_tokens & candidate_tokens

    if not common_tokens:
        return 0

    smaller_count = min(
        len(station_tokens),
        len(candidate_tokens),
    )

    return len(common_tokens) / smaller_count


def get_name_evidence(
    station_name,
    candidate_name,
):
    full_similarity = name_similarity(
        station_name,
        candidate_name,
    )

    token_similarity = get_token_similarity(
        station_name,
        candidate_name,
    )

    final_similarity = max(
        full_similarity,
        token_similarity,
    )

    return {
        "full_similarity": full_similarity,
        "token_similarity": token_similarity,
        "final_similarity": final_similarity,
    }


def get_best_name_match(
    station_name,
    tags,
):
    best_result = None

    for candidate_name in get_candidate_names(tags):
        evidence = get_name_evidence(
            station_name,
            candidate_name,
        )

        if (
            best_result is None
            or evidence["final_similarity"] > best_result["final_similarity"]
        ):
            best_result = {
                "matched_name": candidate_name,
                **evidence,
            }

    return best_result


def candidates_are_duplicates(
    candidate_a,
    candidate_b,
):
    name_a = candidate_a.get("matched_name", "").strip().upper()

    name_b = candidate_b.get("matched_name", "").strip().upper()

    if not name_a or not name_b:
        return False

    if name_a != name_b:
        return False

    distance = distance_miles(
        candidate_a["latitude"],
        candidate_a["longitude"],
        candidate_b["latitude"],
        candidate_b["longitude"],
    )

    return distance <= MAX_DUPLICATE_DISTANCE_MILES


def deduplicate_candidates(
    candidates,
):
    groups = []

    for candidate in candidates:
        matched_group = None

        for group in groups:
            for member in group:
                if candidates_are_duplicates(
                    candidate,
                    member,
                ):
                    matched_group = group
                    break

            if matched_group:
                break

        if matched_group:
            matched_group.append(candidate)
        else:
            groups.append([candidate])

    return groups


def get_representative_coordinates(
    group,
):
    fuel_candidates = [
        candidate for candidate in group if candidate.get("amenity") == "fuel"
    ]

    if fuel_candidates:
        candidates = fuel_candidates

    else:
        service_candidates = [
            candidate for candidate in group if candidate.get("highway") == "services"
        ]

        if service_candidates:
            candidates = service_candidates
        else:
            candidates = group

    latitude = sum(float(candidate["latitude"]) for candidate in candidates) / len(
        candidates
    )

    longitude = sum(float(candidate["longitude"]) for candidate in candidates) / len(
        candidates
    )

    return latitude, longitude


def merge_candidate_group(group):
    if not group:
        return None

    latitude, longitude = get_representative_coordinates(group)

    fuel = any(candidate.get("amenity") == "fuel" for candidate in group)

    services = any(candidate.get("highway") == "services" for candidate in group)

    hgv = any(candidate.get("tags", {}).get("hgv") == "yes" for candidate in group)

    best_candidate = max(
        group,
        key=lambda candidate: candidate.get(
            "similarity",
            0,
        ),
    )

    return {
        "matched_name": (best_candidate.get("matched_name")),
        "similarity": (best_candidate.get("similarity", 0)),
        "latitude": latitude,
        "longitude": longitude,
        "fuel": fuel,
        "services": services,
        "hgv": hgv,
        "member_count": len(group),
        "members": group,
    }


def merge_candidate_groups(groups):
    merged_candidates = []

    for group in groups:
        merged_candidate = merge_candidate_group(group)

        if merged_candidate:
            merged_candidates.append(merged_candidate)

    return merged_candidates


def calculate_strong_location_score(
    distance,
):
    if distance <= 0.5:
        return 40

    if distance <= 1:
        return 35

    if distance <= 2:
        return 25

    if distance <= 5:
        return 10

    return 0


def calculate_city_location_score(
    distance,
):
    if distance <= 1:
        return 20

    if distance <= 3:
        return 15

    if distance <= 5:
        return 10

    if distance <= 10:
        return 5

    return 0


def calculate_location_score(
    distance,
    reference_type,
):
    if reference_type == "city":
        return calculate_city_location_score(distance)

    return calculate_strong_location_score(distance)


def calculate_poi_score(candidate):
    score = 0

    if candidate["fuel"]:
        score += 10

    if candidate["services"]:
        score += 5

    if candidate["hgv"]:
        score += 5

    return score


def calculate_candidate_score(
    candidate,
    reference_type,
):
    name_score = candidate["similarity"] * 40

    location_score = calculate_location_score(
        candidate["location_distance_miles"],
        reference_type,
    )

    poi_score = calculate_poi_score(candidate)

    final_score = name_score + location_score + poi_score

    return {
        "name_score": name_score,
        "location_score": location_score,
        "poi_score": poi_score,
        "final_score": final_score,
    }


def get_decision(
    best,
    margin,
    reference_type,
):
    if reference_type == "city":
        has_strong_name = best["similarity"] >= 0.85

        is_near_city = best["location_distance_miles"] <= 5

        has_poi_evidence = best["poi_score"] > 0

        if (
            best["final_score"] >= 65
            and has_strong_name
            and is_near_city
            and has_poi_evidence
            and margin >= 8
        ):
            return "trusted"

        if best["final_score"] >= 55:
            return "uncertain"

        return "rejected"

    if best["final_score"] >= 80 and margin >= 10:
        return "trusted"

    if best["final_score"] >= 65:
        return "uncertain"

    return "rejected"


def get_exit_reference_point(
    station,
):
    exit_number = extract_exit_number(station.address)

    if not exit_number:
        return None

    exit_candidates = find_exit_candidates(
        station.state,
        exit_number,
    )

    if not exit_candidates:
        return None

    exit_groups = cluster_exit_candidates(exit_candidates)

    city_location = geocode(f"{station.city}, " f"{station.state}")

    if not city_location:
        return None

    cluster_results = []

    for group in exit_groups:
        latitude, longitude = get_exit_cluster_coordinates(group)

        city_distance = distance_miles(
            city_location["lat"],
            city_location["lon"],
            latitude,
            longitude,
        )

        cluster_results.append(
            {
                "latitude": latitude,
                "longitude": longitude,
                "city_distance": (city_distance),
            }
        )

    if not cluster_results:
        return None

    cluster_results.sort(key=lambda cluster: cluster["city_distance"])

    best_cluster = cluster_results[0]

    return {
        "type": "exit",
        "latitude": (best_cluster["latitude"]),
        "longitude": (best_cluster["longitude"]),
        "description": (f"Exit {exit_number}"),
    }


def get_intersection_reference_point(
    station,
):
    if not has_highway_intersection(station.address):
        return None

    result = find_intersection_location(
        station.name,
        station.address,
        station.city,
        station.state,
    )

    if not result:
        return None

    best = result["best"]

    return {
        "type": "intersection",
        "latitude": best["latitude"],
        "longitude": best["longitude"],
        "description": station.address,
    }


def get_city_reference_point(
    station,
):
    city_location = geocode(f"{station.city}, " f"{station.state}")

    if not city_location:
        return None

    return {
        "type": "city",
        "latitude": city_location["lat"],
        "longitude": city_location["lon"],
        "description": (f"{station.city}, " f"{station.state}"),
    }


def get_reference_point(station):
    exit_reference = get_exit_reference_point(station)

    if exit_reference:
        return exit_reference

    intersection_reference = get_intersection_reference_point(station)

    if intersection_reference:
        return intersection_reference

    return get_city_reference_point(station)


def build_osm_candidates(
    station,
    osm_data,
):
    candidates = []

    for element in osm_data.get(
        "elements",
        [],
    ):
        tags = element.get(
            "tags",
            {},
        )

        name_match = get_best_name_match(
            station.name,
            tags,
        )

        if not name_match:
            continue

        latitude, longitude = get_coordinates(element)

        if latitude is None or longitude is None:
            continue

        candidates.append(
            {
                "similarity": (name_match["final_similarity"]),
                "matched_name": (name_match["matched_name"]),
                "latitude": latitude,
                "longitude": longitude,
                "amenity": tags.get("amenity"),
                "highway": tags.get("highway"),
                "osm_id": element.get("id"),
                "osm_type": element.get("type"),
                "tags": tags,
            }
        )

    return candidates


def match_station(station):
    reference = get_reference_point(station)

    if not reference:
        return {
            "decision": "rejected",
            "station": station,
            "reason": ("No geographic " "reference point."),
        }

    osm_data = fetch_state_fuel_candidates(station.state)

    candidates = build_osm_candidates(
        station,
        osm_data,
    )

    groups = deduplicate_candidates(candidates)

    merged_candidates = merge_candidate_groups(groups)

    for candidate in merged_candidates:
        candidate["location_distance_miles"] = distance_miles(
            reference["latitude"],
            reference["longitude"],
            candidate["latitude"],
            candidate["longitude"],
        )

        score = calculate_candidate_score(
            candidate,
            reference["type"],
        )

        candidate.update(score)

    merged_candidates.sort(
        key=lambda candidate: (
            candidate["final_score"],
            -candidate["location_distance_miles"],
        ),
        reverse=True,
    )

    if not merged_candidates:
        return {
            "decision": "rejected",
            "station": station,
            "reference": reference,
            "reason": ("No OSM candidates."),
        }

    best = merged_candidates[0]

    if len(merged_candidates) >= 2:
        second = merged_candidates[1]

        margin = best["final_score"] - second["final_score"]
    else:
        margin = best["final_score"]

    decision = get_decision(
        best,
        margin,
        reference["type"],
    )

    return {
        "decision": decision,
        "station": station,
        "reference": reference,
        "best_match": best,
        "margin": margin,
    }
