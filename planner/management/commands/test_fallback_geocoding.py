import re
import time

import requests

from django.core.management.base import BaseCommand

from planner.models import FuelStation

from planner.geocoding import score_geocode_result

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def clean_address(address):
    """
    Clean highway-style addresses before sending them to Nominatim.

    Example:
    I-44, EXIT 283 & US-69
    becomes:
    I-44 & US-69
    """

    cleaned = address.upper()

    # Remove exit numbers such as "EXIT 283"
    cleaned = re.sub(
        r",?\s*EXIT\s+\d+",
        "",
        cleaned,
    )

    # Convert "/" between road names to "&"
    cleaned = cleaned.replace("/", " & ")

    # Remove extra spaces
    cleaned = re.sub(
        r"\s+",
        " ",
        cleaned,
    )

    return cleaned.strip(" ,")


def search_nominatim(query, headers):
    """
    Send one search request to Nominatim.
    """

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


def print_result(command, station, result):
    command.stdout.write(f"Coordinates: {result['lat']}, {result['lon']}")

    command.stdout.write(f"OSM: {result.get('display_name')}")

    command.stdout.write(f"Category: {result.get('category')}")

    command.stdout.write(f"Type: {result.get('type')}")

    command.stdout.write(f"Address type: {result.get('addresstype')}")

    score_result = score_geocode_result(
        station,
        result,
    )

    command.stdout.write(f"Confidence score: {score_result['score']}")

    command.stdout.write(f"Status: {score_result['status']}")

    command.stdout.write(f"Name similarity: " f"{score_result['name_similarity']}")

    command.stdout.write("Reasons:")

    for reason in score_result["reasons"]:
        command.stdout.write(f"  - {reason}")


class Command(BaseCommand):
    help = "Test improved Nominatim fallback geocoding."

    def handle(self, *args, **options):

        # Only test unresolved stations for now.
        # We deliberately limit this to 10 records.
        stations = FuelStation.objects.filter(geocode_status="pending")[:10]

        headers = {"User-Agent": "spotter-fuel-route-assessment/1.0"}

        for station in stations:

            self.stdout.write(f"\nStation: {station.name}")

            # ---------------------------------
            # Strategy 1: Search by station name
            # ---------------------------------

            name_query = f"{station.name}, " f"{station.city}, " f"{station.state}, USA"

            results = search_nominatim(
                name_query,
                headers,
            )

            if results:

                result = results[0]

                self.stdout.write(self.style.SUCCESS("FOUND BY NAME"))

                self.stdout.write(f"Query: {name_query}")

                print_result(
                    self,
                    station,
                    result,
                )

                # Respect Nominatim rate limit
                time.sleep(1.1)

                continue

            # Wait before trying the second request
            time.sleep(1.1)

            # ---------------------------------
            # Strategy 2: Clean highway address
            # ---------------------------------

            cleaned_address = clean_address(station.address)

            address_query = (
                f"{cleaned_address}, " f"{station.city}, " f"{station.state}, USA"
            )

            results = search_nominatim(
                address_query,
                headers,
            )

            if results:

                result = results[0]

                self.stdout.write(self.style.SUCCESS("FOUND BY CLEANED ADDRESS"))

                self.stdout.write(f"Query: {address_query}")

                print_result(
                    self,
                    station,
                    result,
                )

            else:

                self.stdout.write(self.style.WARNING("NOT FOUND"))

                self.stdout.write(f"Name query: {name_query}")

                self.stdout.write(f"Address query: {address_query}")

            # Respect Nominatim rate limit
            time.sleep(1.1)
