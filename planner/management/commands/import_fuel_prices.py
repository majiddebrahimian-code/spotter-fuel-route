import csv
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from planner.models import FuelPrice, FuelStation

US_STATES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}


class Command(BaseCommand):
    help = "Import fuel stations and prices from the assessment CSV file."

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str)

    def handle(self, *args, **options):
        file_path = Path(options["file_path"])

        if not file_path.exists():
            raise CommandError(f"File not found: {file_path}")

        if FuelStation.objects.exists():
            raise CommandError("Fuel station data already exists in the database.")

        station_count = 0
        price_count = 0
        skipped_count = 0

        with file_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)

            with transaction.atomic():
                for row in reader:
                    state = row["State"].strip().upper()

                    if state not in US_STATES:
                        skipped_count += 1
                        continue

                    station, created = FuelStation.objects.get_or_create(
                        opis_id=int(row["OPIS Truckstop ID"]),
                        defaults={
                            "name": row["Truckstop Name"].strip(),
                            "address": row["Address"].strip(),
                            "city": row["City"].strip(),
                            "state": state,
                            "rack_id": int(row["Rack ID"]),
                        },
                    )

                    if created:
                        station_count += 1

                    FuelPrice.objects.create(
                        station=station,
                        price=Decimal(row["Retail Price"]),
                    )

                    price_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete: "
                f"{station_count} stations, "
                f"{price_count} prices, "
                f"{skipped_count} non-US rows skipped."
            )
        )
