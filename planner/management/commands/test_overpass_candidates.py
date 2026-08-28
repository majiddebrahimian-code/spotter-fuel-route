from django.core.management.base import BaseCommand

from planner.geocoding import name_similarity
from planner.models import FuelStation
from planner.services.geocoding import geocode
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
    names = [
        tags.get("name"),
        tags.get("brand"),
        tags.get("operator"),
    ]

    return [name for name in names if name]


def get_best_name_match(station_name, tags):
    candidate_names = get_candidate_names(tags)

    if not candidate_names:
        return 0, ""

    best_score = 0
    best_name = ""

    for candidate_name in candidate_names:
        similarity = name_similarity(
            station_name,
            candidate_name,
        )

        if similarity > best_score:
            best_score = similarity
            best_name = candidate_name

    return best_score, best_name


class Command(BaseCommand):
    help = "Test OSM candidate matching for a Spotter fuel station."

    def add_arguments(self, parser):
        parser.add_argument(
            "--opis-id",
            type=int,
            help="OPIS Truckstop ID of the station to test.",
        )

    def handle(self, *args, **options):
        opis_id = options.get("opis_id")

        if opis_id:
            station = FuelStation.objects.filter(opis_id=opis_id).first()

            if not station:
                self.stdout.write(
                    self.style.ERROR(f"No station found with OPIS ID {opis_id}.")
                )
                return

        else:
            station = FuelStation.objects.filter(name="WOODSHED OF BIG CABIN").first()

            if not station:
                self.stdout.write(
                    self.style.ERROR("Default test station was not found.")
                )
                return

        self.stdout.write(self.style.SUCCESS(f"\nStation: {station.name}"))

        self.stdout.write(f"OPIS ID: {station.opis_id}")

        self.stdout.write(f"Address: {station.address}")

        self.stdout.write(f"Location: {station.city}, {station.state}")

        city_location = geocode(f"{station.city}, {station.state}")

        if not city_location:
            self.stdout.write(self.style.ERROR("Could not find city coordinates."))
            return

        self.stdout.write(
            f"City coordinates: " f"{city_location['lat']}, " f"{city_location['lon']}"
        )

        data = fetch_state_fuel_candidates(station.state)

        elements = data.get(
            "elements",
            [],
        )

        self.stdout.write(f"OSM candidates found: {len(elements)}")

        ranked_candidates = []

        for element in elements:
            tags = element.get(
                "tags",
                {},
            )

            similarity, matched_name = get_best_name_match(
                station.name,
                tags,
            )

            if not matched_name:
                continue

            latitude, longitude = get_coordinates(element)

            if latitude is None or longitude is None:
                continue

            distance = distance_miles(
                city_location["lat"],
                city_location["lon"],
                latitude,
                longitude,
            )

            ranked_candidates.append(
                {
                    "similarity": similarity,
                    "distance_miles": distance,
                    "matched_name": matched_name,
                    "latitude": latitude,
                    "longitude": longitude,
                    "city": tags.get("addr:city"),
                    "amenity": tags.get("amenity"),
                    "highway": tags.get("highway"),
                    "brand": tags.get("brand"),
                    "operator": tags.get("operator"),
                    "osm_id": element.get("id"),
                    "osm_type": element.get("type"),
                    "tags": tags,
                }
            )

        ranked_candidates.sort(
            key=lambda item: item["similarity"],
            reverse=True,
        )

        groups = deduplicate_candidates(ranked_candidates)

        merged_candidates = merge_candidate_groups(groups)

        self.stdout.write(f"\nCandidate groups: {len(groups)}")

        self.stdout.write(f"Merged candidates: {len(merged_candidates)}")

        merged_candidates.sort(
            key=lambda candidate: (
                candidate.get("similarity", 0),
                -distance_miles(
                    city_location["lat"],
                    city_location["lon"],
                    candidate["latitude"],
                    candidate["longitude"],
                ),
            ),
            reverse=True,
        )

        self.stdout.write("\nTop merged candidates:")

        for candidate in merged_candidates[:10]:
            distance = distance_miles(
                city_location["lat"],
                city_location["lon"],
                candidate["latitude"],
                candidate["longitude"],
            )

            self.stdout.write(
                "\n"
                f"Name: {candidate['matched_name']}\n"
                f"Similarity: "
                f"{candidate['similarity']:.2f}\n"
                f"Distance: {distance:.2f} miles\n"
                f"Fuel: {candidate['fuel']}\n"
                f"Services: {candidate['services']}\n"
                f"HGV: {candidate['hgv']}\n"
                f"Members: "
                f"{candidate['member_count']}\n"
                f"Coordinates: "
                f"{candidate['latitude']:.6f}, "
                f"{candidate['longitude']:.6f}\n"
            )

            self.stdout.write("OSM tags:")

            for member in candidate["members"]:
                self.stdout.write(
                    f"  {member['osm_type']} "
                    f"{member['osm_id']}: "
                    f"{member['tags']}"
                )

            if candidate["member_count"] > 1:
                self.stdout.write("OSM members:")

                for member in candidate["members"]:
                    self.stdout.write(
                        f"  - {member['osm_type']} "
                        f"{member['osm_id']} | "
                        f"amenity={member['amenity']} | "
                        f"highway={member['highway']} | "
                        f"hgv="
                        f"{member['tags'].get('hgv')}"
                    )
