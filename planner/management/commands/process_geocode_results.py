import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from planner.models import FuelStation


class Command(BaseCommand):
    help = "Validate Census geocoding results and update trusted station coordinates."

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            default="data/geocode_results.csv",
        )

    def handle(self, *args, **options):
        input_path = Path(options["input"])

        if not input_path.exists():
            raise CommandError(f"Geocoding result file not found: {input_path}")

        exact_count = 0
        non_exact_count = 0
        rejected_count = 0
        missing_station_count = 0

        with input_path.open(
            "r",
            encoding="utf-8",
            newline="",
        ) as csv_file:
            reader = csv.reader(csv_file)

            with transaction.atomic():
                for row in reader:
                    if len(row) < 6:
                        rejected_count += 1
                        continue

                    opis_id = int(row[0])
                    match_status = row[2].strip()
                    match_type = row[3].strip()

                    try:
                        station = FuelStation.objects.get(opis_id=opis_id)
                    except FuelStation.DoesNotExist:
                        missing_station_count += 1
                        continue

                    if match_status != "Match":
                        rejected_count += 1
                        continue

                    matched_address = row[4].strip()
                    coordinates = row[5].strip()

                    if not coordinates:
                        rejected_count += 1
                        continue

                    try:
                        longitude, latitude = coordinates.split(",")
                    except ValueError:
                        rejected_count += 1
                        continue

                    if match_type == "Exact":
                        station.latitude = latitude
                        station.longitude = longitude
                        station.geocode_status = "exact"
                        station.save(
                            update_fields=[
                                "latitude",
                                "longitude",
                                "geocode_status",
                            ]
                        )

                        exact_count += 1
                        continue

                    if match_type == "Non_Exact":
                        station_city = station.city.strip().lower()
                        station_state = station.state.strip().lower()

                        address_parts = [
                            part.strip().lower() for part in matched_address.split(",")
                        ]

                        city_matches = station_city in address_parts
                        state_matches = station_state in address_parts

                        if city_matches and state_matches:
                            station.latitude = latitude
                            station.longitude = longitude
                            station.geocode_status = "non_exact"
                            station.save(
                                update_fields=[
                                    "latitude",
                                    "longitude",
                                    "geocode_status",
                                ]
                            )

                            non_exact_count += 1
                        else:
                            rejected_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed results: "
                f"{exact_count} exact, "
                f"{non_exact_count} trusted non-exact, "
                f"{rejected_count} unresolved, "
                f"{missing_station_count} station IDs not found."
            )
        )
