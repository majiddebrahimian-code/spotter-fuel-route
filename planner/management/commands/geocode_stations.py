from pathlib import Path

import requests

from django.core.management.base import BaseCommand, CommandError

CENSUS_URL = "https://geocoding.geo.census.gov/" "geocoder/locations/addressbatch"


class Command(BaseCommand):
    help = "Send fuel station addresses to the Census batch geocoder."

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            default="data/geocode_batch.csv",
        )

        parser.add_argument(
            "--output",
            default="data/geocode_results.csv",
        )

    def handle(self, *args, **options):
        input_path = Path(options["input"])
        output_path = Path(options["output"])

        if not input_path.exists():
            raise CommandError(f"Batch file not found: {input_path}")

        with input_path.open("rb") as batch_file:
            response = requests.post(
                CENSUS_URL,
                files={
                    "addressFile": (
                        input_path.name,
                        batch_file,
                        "text/csv",
                    )
                },
                data={
                    "benchmark": "Public_AR_Current",
                },
                timeout=120,
            )

        response.raise_for_status()

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path.write_bytes(response.content)

        self.stdout.write(
            self.style.SUCCESS(f"Geocoding response saved to {output_path}")
        )
