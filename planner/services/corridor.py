from math import cos, radians

from planner.services.osm import distance_miles

MAX_ROUTE_DISTANCE_MILES = 5.0


def point_to_segment_distance(
    point_lat,
    point_lon,
    start_lat,
    start_lon,
    end_lat,
    end_lon,
):
    reference_lat = (point_lat + start_lat + end_lat) / 3

    miles_per_latitude = 69.0

    miles_per_longitude = 69.0 * cos(radians(reference_lat))

    point_x = point_lon * miles_per_longitude
    point_y = point_lat * miles_per_latitude

    start_x = start_lon * miles_per_longitude
    start_y = start_lat * miles_per_latitude

    end_x = end_lon * miles_per_longitude
    end_y = end_lat * miles_per_latitude

    segment_x = end_x - start_x
    segment_y = end_y - start_y

    segment_length_squared = segment_x**2 + segment_y**2

    if segment_length_squared == 0:
        distance = ((point_x - start_x) ** 2 + (point_y - start_y) ** 2) ** 0.5

        return distance, 0

    projection = (
        ((point_x - start_x) * segment_x) + ((point_y - start_y) * segment_y)
    ) / segment_length_squared

    projection = max(
        0,
        min(1, projection),
    )

    closest_x = start_x + projection * segment_x

    closest_y = start_y + projection * segment_y

    distance = ((point_x - closest_x) ** 2 + (point_y - closest_y) ** 2) ** 0.5

    return distance, projection


def find_station_on_route(
    station_lat,
    station_lon,
    route_coordinates,
):
    if len(route_coordinates) < 2:
        return None

    best_distance = None
    best_route_mile = None

    traveled_miles = 0

    for index in range(len(route_coordinates) - 1):
        start_lon, start_lat = route_coordinates[index]

        end_lon, end_lat = route_coordinates[index + 1]

        segment_length = distance_miles(
            start_lat,
            start_lon,
            end_lat,
            end_lon,
        )

        distance, projection = point_to_segment_distance(
            float(station_lat),
            float(station_lon),
            start_lat,
            start_lon,
            end_lat,
            end_lon,
        )

        route_mile = traveled_miles + (segment_length * projection)

        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_route_mile = route_mile

        traveled_miles += segment_length

    return {
        "distance_from_route_miles": (best_distance),
        "route_mile": (best_route_mile),
    }


def is_station_near_route(
    station_lat,
    station_lon,
    route_coordinates,
    max_distance=MAX_ROUTE_DISTANCE_MILES,
):
    position = find_station_on_route(
        station_lat,
        station_lon,
        route_coordinates,
    )

    if not position:
        return False

    return position["distance_from_route_miles"] <= max_distance


def filter_stations_near_route(
    stations,
    route_coordinates,
    max_distance=MAX_ROUTE_DISTANCE_MILES,
):
    results = []

    for station in stations:
        latitude = station.get("latitude")

        longitude = station.get("longitude")

        if latitude is None or longitude is None:
            continue

        position = find_station_on_route(
            latitude,
            longitude,
            route_coordinates,
        )

        if not position:
            continue

        if position["distance_from_route_miles"] > max_distance:
            continue

        results.append(
            {
                **station,
                **position,
            }
        )

    results.sort(key=lambda station: station["route_mile"])

    return results
