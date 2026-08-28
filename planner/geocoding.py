import re
from difflib import SequenceMatcher

STRONG_POI_TYPES = {
    ("amenity", "fuel"),
    ("highway", "services"),
}

MEDIUM_POI_TYPES = {
    ("shop", "convenience"),
}


def normalize_name(name):
    if not name:
        return ""

    name = name.upper()

    # Remove branch/store numbers such as #796 or #1243
    name = re.sub(r"#\s*\d+", "", name)

    # Remove common punctuation
    name = re.sub(r"[^\w\s]", " ", name)

    # Remove extra spaces
    name = re.sub(r"\s+", " ", name)

    return name.strip()


def name_similarity(station_name, result_name):
    station_name = normalize_name(station_name)
    result_name = normalize_name(result_name)

    if not station_name or not result_name:
        return 0.0

    return SequenceMatcher(
        None,
        station_name,
        result_name,
    ).ratio()


def get_result_city(result):
    address = result.get("address", {})

    return (
        (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or ""
        )
        .strip()
        .lower()
    )


def get_result_state_code(result):
    address = result.get("address", {})

    iso_code = address.get("ISO3166-2-lvl4", "")

    # Example:
    # US-WI -> WI
    if iso_code.startswith("US-"):
        return iso_code[3:].upper()

    return ""


def poi_score(result):
    category = result.get("category", "")
    result_type = result.get("type", "")
    address_type = result.get("addresstype", "")

    pair = (category, result_type)

    if pair in STRONG_POI_TYPES:
        return 30, "strong POI +30"

    if pair in MEDIUM_POI_TYPES:
        return 20, "related POI +20"

    if address_type == "road":
        return 5, "road-level result +5"

    return 0, "no useful POI match"


def score_geocode_result(station, result):
    score = 0
    reasons = []

    # -------------------------
    # State validation
    # -------------------------

    result_state = get_result_state_code(result)

    if result_state != station.state.upper():
        return {
            "score": 0,
            "status": "rejected",
            "name_similarity": 0,
            "reasons": ["state mismatch - rejected"],
        }

    score += 10
    reasons.append("state match +10")

    # -------------------------
    # City validation
    # -------------------------

    station_city = station.city.strip().lower()
    result_city = get_result_city(result)

    if result_city == station_city:
        score += 20
        reasons.append("city match +20")

    # -------------------------
    # Station name similarity
    # -------------------------

    result_name = result.get("name", "")

    similarity = name_similarity(
        station.name,
        result_name,
    )

    if similarity >= 0.85:
        score += 40
        reasons.append("high name similarity +40")

    elif similarity >= 0.70:
        score += 28
        reasons.append("medium name similarity +28")

    elif similarity >= 0.55:
        score += 15
        reasons.append("low name similarity +15")

    # -------------------------
    # POI quality
    # -------------------------

    poi_points, poi_reason = poi_score(result)

    score += poi_points
    reasons.append(poi_reason)

    # -------------------------
    # Final classification
    # -------------------------

    if score >= 85 and poi_points > 0:
        status = "trusted"

    elif score >= 65:
        status = "uncertain"

    else:
        status = "rejected"

    return {
        "score": score,
        "status": status,
        "name_similarity": round(similarity, 2),
        "result_city": result_city,
        "result_state": result_state,
        "reasons": reasons,
    }


def clean_address(address):
    if not address:
        return ""

    cleaned = address.upper()

    # I-44, EXIT 283 & US-69
    # -> I-44 & US-69
    cleaned = re.sub(
        r",?\s*EXIT\s+\d+",
        "",
        cleaned,
    )

    cleaned = cleaned.replace("/", " & ")

    cleaned = re.sub(
        r"\s+",
        " ",
        cleaned,
    )

    return cleaned.strip(" ,")
