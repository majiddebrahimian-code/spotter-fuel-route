import time

import requests

from django.core.management.base import BaseCommand

from planner.geocoding import (
    clean_address,
    score_geocode_result,
)
from planner.models import FuelStation

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

REQUEST_DELAY = 1.1


def search_nominatim(query, headers):
    response = requests.get(
        NOMINATIM_URL,
        params={
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": "us",
            "addressdetails": 1,
        },
        headers=headers,
        timeout=20,
    )

    response.raise_for_status()

    return response.json()


class Command(BaseCommand):
    help = "Geocode unresolved fuel stations using Nominatim fallback."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=10,
            help="Maximum number of pending stations to process.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]

        stations = FuelStation.objects.filter(geocode_status="pending").order_by(
            "opis_id"
        )[:limit]

        headers = {"User-Agent": "spotter-fuel-route-assessment/1.0"}

        trusted_count = 0
        failed_count = 0

        for station in stations:
            self.stdout.write(f"\nProcessing: {station.name}")

            result = self.search_by_name(
                station,
                headers,
            )

            if result:
                score_result = score_geocode_result(
                    station,
                    result,
                )

                if score_result["status"] == "trusted":
                    self.save_result(
                        station,
                        result,
                    )

                    trusted_count += 1
                    continue

            result = self.search_by_address(
                station,
                headers,
            )

            if result:
                score_result = score_geocode_result(
                    station,
                    result,
                )

                if score_result["status"] == "trusted":
                    self.save_result(
                        station,
                        result,
                    )

                    trusted_count += 1
                    continue

            station.geocode_status = "failed"
            station.save(update_fields=["geocode_status"])

            failed_count += 1

            self.stdout.write(self.style.WARNING("No trusted location found."))

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                f"Fallback complete: "
                f"{trusted_count} trusted, "
                f"{failed_count} failed."
            )
        )

    def search_by_name(self, station, headers):
        query = f"{station.name}, " f"{station.city}, " f"{station.state}, USA"

        results = search_nominatim(
            query,
            headers,
        )

        time.sleep(REQUEST_DELAY)

        if not results:
            return None

        result = results[0]

        score_result = score_geocode_result(
            station,
            result,
        )

        self.print_score(
            "name",
            query,
            score_result,
        )

        return result

    def search_by_address(self, station, headers):
        cleaned_address = clean_address(station.address)

        if not cleaned_address:
            return None

        query = f"{cleaned_address}, " f"{station.city}, " f"{station.state}, USA"

        results = search_nominatim(
            query,
            headers,
        )

        time.sleep(REQUEST_DELAY)

        if not results:
            return None

        result = results[0]

        score_result = score_geocode_result(
            station,
            result,
        )

        self.print_score(
            "address",
            query,
            score_result,
        )

        return result

    def save_result(self, station, result):
        station.latitude = result["lat"]
        station.longitude = result["lon"]
        station.geocode_status = "fallback"

        station.save(
            update_fields=[
                "latitude",
                "longitude",
                "geocode_status",
            ]
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Trusted location saved: " f"{result['lat']}, " f"{result['lon']}"
            )
        )

    def print_score(
        self,
        strategy,
        query,
        score_result,
    ):
        self.stdout.write(f"Strategy: {strategy}")

        self.stdout.write(f"Query: {query}")

        self.stdout.write(
            f"Score: {score_result['score']} " f"({score_result['status']})"
        )
