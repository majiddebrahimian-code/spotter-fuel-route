from dataclasses import dataclass
from math import cos, radians

from planner.services.osm import distance_miles

MILES_PER_LATITUDE_DEGREE = 69.0

# Projection does not need every point returned by OSRM.
# Keeping roughly this many points makes station matching much faster
# while preserving enough route shape for this assessment.
MAX_PROJECTION_POINTS = 500


@dataclass(frozen=True)
class RouteSegment:
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    length_miles: float
    cumulative_start_miles: float


@dataclass(frozen=True)
class RouteIndex:
    coordinates: tuple
    segments: tuple
    raw_distance_miles: float
    official_distance_miles: float
    mileage_scale: float
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


def _simplify_coordinates(coordinates, max_points):
    """
    Keep a representative subset of route points.

    The first and last points are always preserved.
    """
    if len(coordinates) <= max_points:
        return coordinates

    last_index = len(coordinates) - 1

    selected_indexes = {
        round(index * last_index / (max_points - 1)) for index in range(max_points)
    }

    selected_indexes.add(0)
    selected_indexes.add(last_index)

    return tuple(coordinates[index] for index in sorted(selected_indexes))


def build_route_index(
    route_coordinates,
    official_distance_miles=None,
):
    original_coordinates = tuple(
        (float(lon), float(lat)) for lon, lat in route_coordinates
    )

    if len(original_coordinates) < 2:
        raise ValueError("Route geometry must contain at least two coordinates.")

    coordinates = _simplify_coordinates(
        original_coordinates,
        MAX_PROJECTION_POINTS,
    )

    segments = []
    cumulative_miles = 0.0

    for index in range(len(coordinates) - 1):
        start_lon, start_lat = coordinates[index]
        end_lon, end_lat = coordinates[index + 1]

        segment_length = distance_miles(
            start_lat,
            start_lon,
            end_lat,
            end_lon,
        )

        segments.append(
            RouteSegment(
                start_lat=start_lat,
                start_lon=start_lon,
                end_lat=end_lat,
                end_lon=end_lon,
                length_miles=segment_length,
                cumulative_start_miles=cumulative_miles,
            )
        )

        cumulative_miles += segment_length

    if official_distance_miles is None:
        official_distance = cumulative_miles
    else:
        official_distance = float(official_distance_miles)

    if official_distance <= 0:
        official_distance = cumulative_miles

    if cumulative_miles > 0:
        mileage_scale = official_distance / cumulative_miles
    else:
        mileage_scale = 1.0

    # Use the original geometry for geographic bounds.
    # This avoids changing the database pre-filter.
    latitudes = [lat for _, lat in original_coordinates]

    longitudes = [lon for lon, _ in original_coordinates]

    return RouteIndex(
        coordinates=coordinates,
        segments=tuple(segments),
        raw_distance_miles=cumulative_miles,
        official_distance_miles=official_distance,
        mileage_scale=mileage_scale,
        min_lat=min(latitudes),
        max_lat=max(latitudes),
        min_lon=min(longitudes),
        max_lon=max(longitudes),
    )


def _project_point_to_segment(
    point_lat,
    point_lon,
    segment,
):
    reference_lat = (point_lat + segment.start_lat + segment.end_lat) / 3

    miles_per_longitude_degree = MILES_PER_LATITUDE_DEGREE * cos(radians(reference_lat))

    point_x = point_lon * miles_per_longitude_degree
    point_y = point_lat * MILES_PER_LATITUDE_DEGREE

    start_x = segment.start_lon * miles_per_longitude_degree
    start_y = segment.start_lat * MILES_PER_LATITUDE_DEGREE

    end_x = segment.end_lon * miles_per_longitude_degree
    end_y = segment.end_lat * MILES_PER_LATITUDE_DEGREE

    segment_x = end_x - start_x
    segment_y = end_y - start_y

    segment_length_squared = segment_x**2 + segment_y**2

    if segment_length_squared == 0:
        projection = 0.0
    else:
        projection = (
            ((point_x - start_x) * segment_x) + ((point_y - start_y) * segment_y)
        ) / segment_length_squared

        projection = max(
            0.0,
            min(1.0, projection),
        )

    closest_lat = segment.start_lat + projection * (segment.end_lat - segment.start_lat)

    closest_lon = segment.start_lon + projection * (segment.end_lon - segment.start_lon)

    return (
        projection,
        closest_lat,
        closest_lon,
    )


def project_station_to_route(
    station_lat,
    station_lon,
    route_index,
):
    station_lat = float(station_lat)
    station_lon = float(station_lon)

    best_detour = None
    best_raw_route_mile = None

    for segment in route_index.segments:
        (
            projection,
            closest_lat,
            closest_lon,
        ) = _project_point_to_segment(
            station_lat,
            station_lon,
            segment,
        )

        detour = distance_miles(
            station_lat,
            station_lon,
            closest_lat,
            closest_lon,
        )

        raw_route_mile = (
            segment.cumulative_start_miles + segment.length_miles * projection
        )

        if best_detour is None or detour < best_detour:
            best_detour = detour
            best_raw_route_mile = raw_route_mile

        elif detour == best_detour and raw_route_mile < best_raw_route_mile:
            best_raw_route_mile = raw_route_mile

    if best_detour is None:
        return None

    scaled_route_mile = best_raw_route_mile * route_index.mileage_scale

    scaled_route_mile = max(
        0.0,
        min(
            route_index.official_distance_miles,
            scaled_route_mile,
        ),
    )

    return {
        "route_mile": scaled_route_mile,
        "detour_miles": best_detour,
        "distance_from_route_miles": (best_detour),
    }


def project_stations_to_route(
    stations,
    route_index,
    max_detour_miles=None,
):
    projected = []

    for station in stations:
        latitude = station.get("latitude")
        longitude = station.get("longitude")

        if latitude is None or longitude is None:
            continue

        position = project_station_to_route(
            latitude,
            longitude,
            route_index,
        )

        if position is None:
            continue

        if max_detour_miles is not None and position["detour_miles"] > max_detour_miles:
            continue

        projected.append(
            {
                **station,
                **position,
            }
        )

    projected.sort(
        key=lambda station: (
            station["route_mile"],
            station["detour_miles"],
        )
    )

    return projected


def expanded_route_bounds(
    route_index,
    margin_miles,
):
    margin_miles = float(margin_miles)

    latitude_margin = margin_miles / MILES_PER_LATITUDE_DEGREE

    highest_absolute_latitude = max(
        abs(route_index.min_lat),
        abs(route_index.max_lat),
    )

    longitude_factor = cos(
        radians(
            min(
                highest_absolute_latitude,
                80.0,
            )
        )
    )

    longitude_factor = max(
        longitude_factor,
        0.1,
    )

    longitude_margin = margin_miles / (MILES_PER_LATITUDE_DEGREE * longitude_factor)

    return {
        "min_lat": max(
            -90.0,
            route_index.min_lat - latitude_margin,
        ),
        "max_lat": min(
            90.0,
            route_index.max_lat + latitude_margin,
        ),
        "min_lon": max(
            -180.0,
            route_index.min_lon - longitude_margin,
        ),
        "max_lon": min(
            180.0,
            route_index.max_lon + longitude_margin,
        ),
    }


# Backward-compatible helpers


def find_station_on_route(
    station_lat,
    station_lon,
    route_coordinates,
    official_distance_miles=None,
):
    route_index = build_route_index(
        route_coordinates,
        official_distance_miles=(official_distance_miles),
    )

    return project_station_to_route(
        station_lat,
        station_lon,
        route_index,
    )


def is_station_near_route(
    station_lat,
    station_lon,
    route_coordinates,
    max_distance=None,
    official_distance_miles=None,
):
    position = find_station_on_route(
        station_lat,
        station_lon,
        route_coordinates,
        official_distance_miles=(official_distance_miles),
    )

    if position is None:
        return False

    if max_distance is None:
        return True

    return position["detour_miles"] <= float(max_distance)


def filter_stations_near_route(
    stations,
    route_coordinates,
    max_distance=None,
    official_distance_miles=None,
):
    route_index = build_route_index(
        route_coordinates,
        official_distance_miles=(official_distance_miles),
    )

    return project_stations_to_route(
        stations,
        route_index,
        max_detour_miles=max_distance,
    )
