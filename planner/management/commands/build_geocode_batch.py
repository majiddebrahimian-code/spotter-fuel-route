import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from planner.models import FuelStation


class Command(BaseCommand):
    help = "Build a Census geocoding batch file from fuel stations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default="data/geocode_batch.csv",
        )

    def handle(self, *args, **options):
        output_path = Path(options["output"])
        output_path.parent.mkdir(parents=True, exist_ok=True)

        stations = FuelStation.objects.filter(geocode_status="pending").order_by(
            "opis_id"
        )

        with output_path.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as csv_file:
            writer = csv.writer(csv_file)

            for station in stations:
                writer.writerow(
                    [
                        station.opis_id,
                        station.address,
                        station.city,
                        station.state,
                        "",
                    ]
                )

        self.stdout.write(
            self.style.SUCCESS(f"Created batch file with {stations.count()} stations.")
        )
