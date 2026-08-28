from django.core.management.base import BaseCommand

from planner.geocoding import name_similarity
from planner.models import FuelStation
from planner.services.exits import (
    extract_exit_number,
    find_exit_candidates,
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


def get_best_name_match(
    station_name,
    tags,
):
    best_similarity = 0
    best_name = ""

    for candidate_name in get_candidate_names(tags):
        similarity = name_similarity(
            station_name,
            candidate_name,
        )

        if similarity > best_similarity:
            best_similarity = similarity
            best_name = candidate_name

    return (
        best_similarity,
        best_name,
    )


class Command(BaseCommand):
    help = "Test fuel station matching " "using highway exit information."

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

        self.stdout.write(f"Address: " f"{station.address}")

        self.stdout.write(f"Location: " f"{station.city}, " f"{station.state}")

        exit_number = extract_exit_number(station.address)

        if not exit_number:
            self.stdout.write(self.style.ERROR("No exit number " "found in address."))
            return

        self.stdout.write(f"Exit number: " f"{exit_number}")

        exit_candidates = find_exit_candidates(
            station.state,
            exit_number,
        )

        self.stdout.write(f"Matching OSM exits: " f"{len(exit_candidates)}")

        if not exit_candidates:
            self.stdout.write(self.style.WARNING("No matching exit " "found in OSM."))
            return

        for exit_candidate in exit_candidates:
            self.stdout.write("\nExit candidate:")

            self.stdout.write(f"  OSM ID: " f"{exit_candidate['osm_id']}")

            self.stdout.write(f"  Ref: " f"{exit_candidate['ref']}")

            self.stdout.write(f"  Name: " f"{exit_candidate['name']}")

            self.stdout.write(f"  Destination: " f"{exit_candidate['destination']}")

            self.stdout.write(
                f"  Coordinates: "
                f"{exit_candidate['latitude']}, "
                f"{exit_candidate['longitude']}"
            )

            self.stdout.write(f"  Tags: " f"{exit_candidate['tags']}")

        osm_data = fetch_state_fuel_candidates(station.state)

        ranked_candidates = []

        for element in osm_data.get(
            "elements",
            [],
        ):
            tags = element.get(
                "tags",
                {},
            )

            (
                similarity,
                matched_name,
            ) = get_best_name_match(
                station.name,
                tags,
            )

            if not matched_name:
                continue

            latitude, longitude = get_coordinates(element)

            if latitude is None or longitude is None:
                continue

            ranked_candidates.append(
                {
                    "similarity": similarity,
                    "matched_name": matched_name,
                    "latitude": latitude,
                    "longitude": longitude,
                    "amenity": tags.get("amenity"),
                    "highway": tags.get("highway"),
                    "osm_id": element.get("id"),
                    "osm_type": element.get("type"),
                    "tags": tags,
                }
            )

        groups = deduplicate_candidates(ranked_candidates)

        merged_candidates = merge_candidate_groups(groups)

        best_exit = exit_candidates[0]

        for candidate in merged_candidates:
            candidate["exit_distance_miles"] = distance_miles(
                best_exit["latitude"],
                best_exit["longitude"],
                candidate["latitude"],
                candidate["longitude"],
            )

        merged_candidates.sort(
            key=lambda candidate: (
                -candidate["similarity"],
                candidate["exit_distance_miles"],
            )
        )

        self.stdout.write("\nTop candidates " "using exit distance:")

        for candidate in merged_candidates[:10]:
            self.stdout.write(
                "\n"
                f"Name: "
                f"{candidate['matched_name']}\n"
                f"Similarity: "
                f"{candidate['similarity']:.2f}\n"
                f"Distance from exit: "
                f"{candidate['exit_distance_miles']:.2f} miles\n"
                f"Fuel: "
                f"{candidate['fuel']}\n"
                f"Services: "
                f"{candidate['services']}\n"
                f"HGV: "
                f"{candidate['hgv']}\n"
                f"Coordinates: "
                f"{candidate['latitude']:.6f}, "
                f"{candidate['longitude']:.6f}"
            )
