import requests

GEOCODING_URL = "https://nominatim.openstreetmap.org/search"


def geocode(location):
    params = {
        "q": location,
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }

    headers = {"User-Agent": "spotter-fuel-route/1.0"}

    response = requests.get(
        GEOCODING_URL,
        params=params,
        headers=headers,
        timeout=10,
    )

    response.raise_for_status()

    results = response.json()

    if not results:
        return None

    return {
        "lat": float(results[0]["lat"]),
        "lon": float(results[0]["lon"]),
        "name": results[0]["display_name"],
    }
