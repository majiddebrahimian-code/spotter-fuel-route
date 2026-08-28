import re

from django.core.management.base import BaseCommand

from planner.geocoding import name_similarity
from planner.models import FuelStation

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

from planner.services.matching import (
    deduplicate_candidates,
    merge_candidate_groups,
)

from planner.services.osm import (
    distance_miles,
    fetch_state_fuel_candidates,
    get_coordinates,
)

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
            return "TRUSTED"

        if best["final_score"] >= 55:
            return "UNCERTAIN"

        return "REJECTED"

    if best["final_score"] >= 80 and margin >= 10:
        return "TRUSTED"

    if best["final_score"] >= 65:
        return "UNCERTAIN"

    return "REJECTED"


def get_exit_reference_point(
    station,
    command,
):
    exit_number = extract_exit_number(station.address)

    if not exit_number:
        return None

    command.stdout.write(f"Exit number: {exit_number}")

    exit_candidates = find_exit_candidates(
        station.state,
        exit_number,
    )

    if not exit_candidates:
        command.stdout.write(command.style.WARNING("No matching OSM exit found."))
        return None

    exit_groups = cluster_exit_candidates(exit_candidates)

    command.stdout.write(f"OSM exit objects: " f"{len(exit_candidates)}")

    command.stdout.write(f"Exit clusters: " f"{len(exit_groups)}")

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
                "members": group,
                "latitude": latitude,
                "longitude": longitude,
                "city_distance": city_distance,
            }
        )

    cluster_results.sort(key=lambda cluster: (cluster["city_distance"]))

    command.stdout.write("\nExit clusters:")

    for index, cluster in enumerate(
        cluster_results,
        start=1,
    ):
        command.stdout.write(
            f"#{index} | "
            f"Objects: "
            f"{len(cluster['members'])} | "
            f"Distance from city: "
            f"{cluster['city_distance']:.2f} miles | "
            f"Coordinates: "
            f"{cluster['latitude']:.6f}, "
            f"{cluster['longitude']:.6f}"
        )

    best_cluster = cluster_results[0]

    command.stdout.write("\nSelected exit cluster:")

    command.stdout.write(
        f"Distance from city: " f"{best_cluster['city_distance']:.2f} miles"
    )

    command.stdout.write(
        f"Coordinates: "
        f"{best_cluster['latitude']:.6f}, "
        f"{best_cluster['longitude']:.6f}"
    )

    return {
        "type": "exit",
        "latitude": (best_cluster["latitude"]),
        "longitude": (best_cluster["longitude"]),
        "description": (f"Exit {exit_number}"),
    }


def get_intersection_reference_point(
    station,
    command,
):
    if not has_highway_intersection(station.address):
        return None

    command.stdout.write("\nNo usable exit.")

    command.stdout.write("Trying highway " "intersection matching...")

    result = find_intersection_location(
        station.name,
        station.address,
        station.city,
        station.state,
    )

    if not result:
        command.stdout.write(
            command.style.WARNING("Could not geocode " "highway intersection.")
        )
        return None

    command.stdout.write("\nIntersection candidates:")

    for index, item in enumerate(
        result["results"],
        start=1,
    ):
        command.stdout.write(f"\n#{index}")

        command.stdout.write(f"Query: " f"{item['query']}")

        command.stdout.write(f"Result: " f"{item['name']}")

        command.stdout.write(
            f"Distance from city: " f"{item['city_distance_miles']:.2f} miles"
        )

    best = result["best"]

    command.stdout.write("\nSelected intersection:")

    command.stdout.write(best["name"])

    command.stdout.write(
        f"Coordinates: " f"{best['latitude']:.6f}, " f"{best['longitude']:.6f}"
    )

    return {
        "type": "intersection",
        "latitude": best["latitude"],
        "longitude": best["longitude"],
        "description": station.address,
    }


def get_city_reference_point(
    station,
    command,
):
    command.stdout.write("\nFalling back to " "city-scoped matching...")

    city_location = geocode(f"{station.city}, " f"{station.state}")

    if not city_location:
        command.stdout.write(command.style.WARNING("Could not geocode city."))
        return None

    command.stdout.write(f"City reference: " f"{city_location['name']}")

    command.stdout.write(
        f"City coordinates: "
        f"{city_location['lat']:.6f}, "
        f"{city_location['lon']:.6f}"
    )

    return {
        "type": "city",
        "latitude": city_location["lat"],
        "longitude": city_location["lon"],
        "description": (f"{station.city}, " f"{station.state}"),
    }


def get_reference_point(
    station,
    command,
):
    exit_reference = get_exit_reference_point(
        station,
        command,
    )

    if exit_reference:
        return exit_reference

    intersection_reference = get_intersection_reference_point(
        station,
        command,
    )

    if intersection_reference:
        return intersection_reference

    return get_city_reference_point(
        station,
        command,
    )


class Command(BaseCommand):
    help = "Test the final station " "matching score."

    def add_arguments(
        self,
        parser,
    ):
        parser.add_argument(
            "--opis-id",
            type=int,
            required=True,
        )

    def handle(
        self,
        *args,
        **options,
    ):
        opis_id = options["opis_id"]

        station = FuelStation.objects.filter(opis_id=opis_id).first()

        if not station:
            self.stdout.write(self.style.ERROR("Station not found."))
            return

        self.stdout.write(self.style.SUCCESS(f"\nStation: " f"{station.name}"))

        self.stdout.write(f"OPIS ID: " f"{station.opis_id}")

        self.stdout.write(f"Address: " f"{station.address}")

        self.stdout.write(f"Location: " f"{station.city}, " f"{station.state}")

        tokens = get_meaningful_tokens(station.name)

        self.stdout.write(f"Meaningful name tokens: " f"{sorted(tokens)}")

        reference = get_reference_point(
            station,
            self,
        )

        if not reference:
            self.stdout.write(
                self.style.ERROR(
                    "Could not determine " "a geographic " "reference point."
                )
            )
            return

        self.stdout.write(f"\nGeographic evidence: " f"{reference['type'].upper()}")

        osm_data = fetch_state_fuel_candidates(station.state)

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

        top_candidates = merged_candidates[:5]

        self.stdout.write("\nTop scored candidates:")

        for index, candidate in enumerate(
            top_candidates,
            start=1,
        ):
            evidence = get_name_evidence(
                station.name,
                candidate["matched_name"],
            )

            self.stdout.write(
                "\n"
                f"#{index} "
                f"{candidate['matched_name']}\n"
                f"Full name similarity: "
                f"{evidence['full_similarity']:.2f}\n"
                f"Token similarity: "
                f"{evidence['token_similarity']:.2f}\n"
                f"Final name similarity: "
                f"{candidate['similarity']:.2f}\n"
                f"{reference['type'].title()} distance: "
                f"{candidate['location_distance_miles']:.2f} miles\n"
                f"Fuel: "
                f"{candidate['fuel']}\n"
                f"Services: "
                f"{candidate['services']}\n"
                f"HGV: "
                f"{candidate['hgv']}\n"
                f"Name score: "
                f"{candidate['name_score']:.1f}/40\n"
                f"Location score: "
                f"{candidate['location_score']}\n"
                f"POI score: "
                f"{candidate['poi_score']}/20\n"
                f"FINAL SCORE: "
                f"{candidate['final_score']:.1f}"
            )

        if not top_candidates:
            self.stdout.write(self.style.ERROR("No candidates found."))
            return

        best = top_candidates[0]

        if len(top_candidates) >= 2:
            second = top_candidates[1]

            margin = best["final_score"] - second["final_score"]
        else:
            margin = best["final_score"]

        decision = get_decision(
            best,
            margin,
            reference["type"],
        )

        self.stdout.write("\n-------------------------")

        self.stdout.write(f"GEOGRAPHIC METHOD: " f"{reference['type'].upper()}")

        self.stdout.write(f"BEST MATCH: " f"{best['matched_name']}")

        self.stdout.write(f"BEST SCORE: " f"{best['final_score']:.1f}")

        self.stdout.write(f"MARGIN: " f"{margin:.1f}")

        if decision == "TRUSTED":
            self.stdout.write(self.style.SUCCESS("DECISION: TRUSTED"))

        elif decision == "UNCERTAIN":
            self.stdout.write(self.style.WARNING("DECISION: UNCERTAIN"))

        else:
            self.stdout.write(self.style.ERROR("DECISION: REJECTED"))
