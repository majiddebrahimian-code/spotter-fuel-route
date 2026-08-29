from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

FUEL_STEP_GALLONS = Decimal("0.1")

DEFAULT_MPG = Decimal("10")
DEFAULT_MAX_RANGE_MILES = Decimal("500")

# Raw prices have 6 decimal places, but the median of two prices
# can produce 7 decimal places.
PRICE_SCALE = 10_000_000

# One fuel unit is 0.1 gallon, so monetary calculations need
# one additional decimal place.
COST_TICKS_PER_DOLLAR = 100_000_000

MIN_ROUTE_PROGRESS_MILES = 1e-9


class NoFeasibleFuelPlan(Exception):
    pass


@dataclass(frozen=True)
class FuelNode:
    index: int
    kind: str
    route_mile: float
    detour_miles: float
    price: Decimal | None = None
    station: dict | None = None


@dataclass(frozen=True)
class Edge:
    to_index: int
    distance_miles: float
    fuel_units: int


@dataclass(frozen=True)
class Transition:
    previous_node_index: int
    previous_arrival_fuel_units: int
    departure_fuel_units: int
    purchased_units: int
    edge_distance_miles: float
    edge_fuel_units: int


@dataclass(frozen=True)
class ArrivalState:
    cost_ticks: int
    uncertain_stops: int
    detour_miles: float
    stop_count: int
    predecessor: Transition | None


@dataclass(frozen=True)
class DepartureState:
    cost_ticks: int
    uncertain_stops: int
    detour_miles: float
    stop_count: int
    arrival_fuel_units: int
    departure_fuel_units: int
    purchased_units: int


def _to_decimal(value):
    if isinstance(value, Decimal):
        return value

    return Decimal(str(value))


def _units_to_gallons(units):
    return Decimal(units) * FUEL_STEP_GALLONS


def _gallons_to_units_floor(gallons):
    gallons = _to_decimal(gallons)

    return int((gallons / FUEL_STEP_GALLONS).to_integral_value(rounding=ROUND_FLOOR))


def _fuel_units_for_distance(distance_miles, mpg):
    """
    Calculate fuel conservatively.

    We always round fuel consumption upward so the optimizer never
    creates artificial range through rounding.
    """

    distance = _to_decimal(max(0.0, float(distance_miles)))

    miles_per_fuel_unit = mpg * FUEL_STEP_GALLONS

    units = (distance / miles_per_fuel_unit).to_integral_value(rounding=ROUND_CEILING)

    return int(units)


def _price_to_scaled_integer(price):
    price = _to_decimal(price)

    scaled = price * Decimal(PRICE_SCALE)
    integral = scaled.to_integral_value()

    if scaled != integral:
        raise ValueError("Fuel price precision exceeds supported precision.")

    return int(integral)


def _ticks_to_dollars(ticks):
    return Decimal(ticks) / Decimal(COST_TICKS_PER_DOLLAR)


def _state_key(state):
    return (
        state.cost_ticks,
        state.uncertain_stops,
        state.detour_miles,
        state.stop_count,
    )


def _build_nodes(
    route_distance_miles,
    stations,
):
    """
    Build a forward-only list:

        Start
        Station
        Station
        ...
        Destination
    """

    route_distance = float(route_distance_miles)

    station_nodes = []

    for station in stations:
        price = station.get("price")
        route_mile = station.get("route_mile")
        detour_miles = station.get("detour_miles")

        if price is None or route_mile is None or detour_miles is None:
            continue

        price = _to_decimal(price)
        route_mile = float(route_mile)
        detour_miles = float(detour_miles)

        if price <= 0:
            continue

        if detour_miles < 0:
            continue

        # A station at the exact start is useless because we begin
        # with the configured initial fuel.
        if route_mile <= MIN_ROUTE_PROGRESS_MILES:
            continue

        # Buying fuel at or beyond the destination is never useful.
        if route_mile >= route_distance - MIN_ROUTE_PROGRESS_MILES:
            continue

        station_identifier = str(
            station.get("station_id") or station.get("opis_id") or ""
        )

        station_nodes.append(
            (
                route_mile,
                detour_miles,
                station_identifier,
                price,
                station,
            )
        )

    station_nodes.sort(
        key=lambda item: (
            item[0],
            item[1],
            item[2],
        )
    )

    nodes = [
        FuelNode(
            index=0,
            kind="start",
            route_mile=0.0,
            detour_miles=0.0,
        )
    ]

    for (
        route_mile,
        detour_miles,
        _,
        price,
        station,
    ) in station_nodes:
        nodes.append(
            FuelNode(
                index=len(nodes),
                kind="station",
                route_mile=route_mile,
                detour_miles=detour_miles,
                price=price,
                station=station,
            )
        )

    nodes.append(
        FuelNode(
            index=len(nodes),
            kind="destination",
            route_mile=route_distance,
            detour_miles=0.0,
        )
    )

    return nodes


def _build_reachability_graph(
    nodes,
    capacity_units,
    mpg,
):
    """
    Pre-calculate which later nodes are reachable from each node.

    Travel distance:

        current detour
        + forward route distance
        + next detour
    """

    graph = [[] for _ in nodes]

    maximum_driving_miles = float(_units_to_gallons(capacity_units) * mpg)

    for current_index, current in enumerate(nodes[:-1]):
        for next_index in range(
            current_index + 1,
            len(nodes),
        ):
            next_node = nodes[next_index]

            route_progress = next_node.route_mile - current.route_mile

            # Do not chain stations that project to effectively
            # the same position on the route.
            if route_progress <= MIN_ROUTE_PROGRESS_MILES:
                continue

            # next_node.detour is always non-negative.
            # Once route progress itself is too far, every later
            # node is also unreachable.
            minimum_possible_distance = current.detour_miles + route_progress

            if (
                minimum_possible_distance
                > maximum_driving_miles + MIN_ROUTE_PROGRESS_MILES
            ):
                break

            distance_miles = (
                current.detour_miles + route_progress + next_node.detour_miles
            )

            required_fuel_units = _fuel_units_for_distance(
                distance_miles,
                mpg,
            )

            if required_fuel_units > capacity_units:
                continue

            graph[current_index].append(
                Edge(
                    to_index=next_index,
                    distance_miles=distance_miles,
                    fuel_units=required_fuel_units,
                )
            )

    return graph


def _build_departure_states(
    node,
    arrival_states,
    capacity_units,
):
    """
    Convert arrival fuel states into departure fuel states.

    For a station, at least one fuel unit (0.1 gallon) must be
    purchased. This prevents meaningless zero-purchase stops.

    A prefix minimum keeps this operation O(capacity) rather than
    O(capacity²).
    """

    departures = [None for _ in range(capacity_units + 1)]

    if node.kind == "start":
        for fuel_units, state in enumerate(arrival_states):
            if state is None:
                continue

            departures[fuel_units] = DepartureState(
                cost_ticks=state.cost_ticks,
                uncertain_stops=(state.uncertain_stops),
                detour_miles=state.detour_miles,
                stop_count=state.stop_count,
                arrival_fuel_units=fuel_units,
                departure_fuel_units=fuel_units,
                purchased_units=0,
            )

        return departures

    if node.kind != "station":
        return departures

    price_scaled = _price_to_scaled_integer(node.price)

    is_uncertain = node.station.get("geocode_status") == "uncertain"

    best_prefix = None

    for departure_units in range(
        1,
        capacity_units + 1,
    ):
        # purchase >= 1 unit means:
        #
        # arrival_units < departure_units
        #
        # As departure increases, add one new arrival state
        # to the prefix candidate set.
        arrival_units = departure_units - 1
        arrival_state = arrival_states[arrival_units]

        if arrival_state is not None:
            adjusted_cost = arrival_state.cost_ticks - arrival_units * price_scaled

            candidate_key = (
                adjusted_cost,
                arrival_state.uncertain_stops,
                arrival_state.detour_miles,
                arrival_state.stop_count,
                # Purely deterministic final tie-break.
                -arrival_units,
            )

            if best_prefix is None or candidate_key < best_prefix["key"]:
                best_prefix = {
                    "key": candidate_key,
                    "state": arrival_state,
                    "arrival_units": (arrival_units),
                    "adjusted_cost": (adjusted_cost),
                }

        if best_prefix is None:
            continue

        base_state = best_prefix["state"]

        chosen_arrival_units = best_prefix["arrival_units"]

        purchased_units = departure_units - chosen_arrival_units

        total_cost = best_prefix["adjusted_cost"] + departure_units * price_scaled

        departures[departure_units] = DepartureState(
            cost_ticks=total_cost,
            uncertain_stops=(base_state.uncertain_stops + int(is_uncertain)),
            detour_miles=(base_state.detour_miles + node.detour_miles),
            stop_count=(base_state.stop_count + 1),
            arrival_fuel_units=(chosen_arrival_units),
            departure_fuel_units=(departure_units),
            purchased_units=purchased_units,
        )

    return departures


def _find_best_destination_state(
    destination_states,
):
    best = None

    for fuel_units, state in enumerate(destination_states):
        if state is None:
            continue

        # Final optimizer priority:
        #
        # 1. fuel cost
        # 2. fewer uncertain stations
        # 3. less detour
        # 4. less fuel remaining
        # 5. fewer stops
        final_key = (
            state.cost_ticks,
            state.uncertain_stops,
            state.detour_miles * 2,
            fuel_units,
            state.stop_count,
        )

        if best is None or final_key < best["key"]:
            best = {
                "key": final_key,
                "fuel_units": fuel_units,
                "state": state,
            }

    return best


def _node_label(node):
    if node.kind == "start":
        return "start"

    if node.kind == "destination":
        return "destination"

    return node.station.get("name") or f"station-{node.station.get('opis_id')}"


def _reconstruct_plan(
    nodes,
    states,
    destination_fuel_units,
):
    current_node_index = len(nodes) - 1
    current_fuel_units = destination_fuel_units

    fuel_stops = []
    travel_legs = []

    total_purchased_units = 0

    while current_node_index != 0:
        current_state = states[current_node_index][current_fuel_units]

        if current_state is None:
            raise RuntimeError("Broken optimizer state during reconstruction.")

        transition = current_state.predecessor

        if transition is None:
            raise RuntimeError("Missing optimizer predecessor.")

        previous_node = nodes[transition.previous_node_index]

        current_node = nodes[current_node_index]

        travel_legs.append(
            {
                "from": _node_label(previous_node),
                "to": _node_label(current_node),
                "distance_miles": (transition.edge_distance_miles),
                "fuel_consumed_gallons": (
                    _units_to_gallons(transition.edge_fuel_units)
                ),
            }
        )

        if previous_node.kind == "station":
            price_scaled = _price_to_scaled_integer(previous_node.price)

            stop_cost_ticks = transition.purchased_units * price_scaled

            station = previous_node.station

            fuel_stops.append(
                {
                    "station_id": (station.get("station_id")),
                    "opis_id": (station.get("opis_id")),
                    "name": station.get("name"),
                    "address": station.get("address"),
                    "city": station.get("city"),
                    "state": station.get("state"),
                    "latitude": (station.get("latitude")),
                    "longitude": (station.get("longitude")),
                    "geocode_status": (station.get("geocode_status")),
                    "match_score": (station.get("match_score")),
                    "match_margin": (station.get("match_margin")),
                    "route_mile": (previous_node.route_mile),
                    "detour_miles": (previous_node.detour_miles),
                    "price_per_gallon": (previous_node.price),
                    "fuel_on_arrival_gallons": (
                        _units_to_gallons(transition.previous_arrival_fuel_units)
                    ),
                    "gallons_purchased": (
                        _units_to_gallons(transition.purchased_units)
                    ),
                    "fuel_on_departure_gallons": (
                        _units_to_gallons(transition.departure_fuel_units)
                    ),
                    "stop_cost": (_ticks_to_dollars(stop_cost_ticks)),
                }
            )

            total_purchased_units += transition.purchased_units

        current_node_index = transition.previous_node_index

        current_fuel_units = transition.previous_arrival_fuel_units

    fuel_stops.reverse()
    travel_legs.reverse()

    return {
        "fuel_stops": fuel_stops,
        "travel_legs": travel_legs,
        "total_purchased_units": (total_purchased_units),
    }


def optimize_fuel_plan(
    route_distance_miles,
    stations,
    mpg=DEFAULT_MPG,
    max_range_miles=DEFAULT_MAX_RANGE_MILES,
    initial_fuel_gallons=None,
):
    """
    Find the minimum-cost fuel plan for one fixed OSRM route.
    """

    route_distance = float(route_distance_miles)

    if route_distance < 0:
        raise ValueError("Route distance cannot be negative.")

    mpg = _to_decimal(mpg)
    max_range_miles = _to_decimal(max_range_miles)

    if mpg <= 0:
        raise ValueError("MPG must be greater than zero.")

    if max_range_miles <= 0:
        raise ValueError("Maximum range must be greater than zero.")

    tank_capacity_gallons = max_range_miles / mpg

    capacity_units = _gallons_to_units_floor(tank_capacity_gallons)

    if capacity_units <= 0:
        raise ValueError("Tank capacity is too small.")

    if initial_fuel_gallons is None:
        initial_units = capacity_units
    else:
        initial_fuel = _to_decimal(initial_fuel_gallons)

        if initial_fuel < 0:
            raise ValueError("Initial fuel cannot be negative.")

        if initial_fuel > tank_capacity_gallons:
            raise ValueError("Initial fuel cannot exceed tank capacity.")

        initial_units = _gallons_to_units_floor(initial_fuel)

        initial_units = min(
            initial_units,
            capacity_units,
        )

    if route_distance == 0:
        return {
            "total_cost": Decimal("0"),
            "initial_fuel_gallons": (_units_to_gallons(initial_units)),
            "tank_capacity_gallons": (_units_to_gallons(capacity_units)),
            "total_fuel_purchased_gallons": (Decimal("0")),
            "fuel_remaining_gallons": (_units_to_gallons(initial_units)),
            "base_route_distance_miles": 0.0,
            "estimated_detour_miles": 0.0,
            "estimated_total_distance_miles": 0.0,
            "uncertain_stops": 0,
            "uses_uncertain_stations": False,
            "fuel_stops": [],
            "travel_legs": [],
        }

    nodes = _build_nodes(
        route_distance,
        stations,
    )

    graph = _build_reachability_graph(
        nodes,
        capacity_units,
        mpg,
    )

    states = [[None for _ in range(capacity_units + 1)] for _ in nodes]

    states[0][initial_units] = ArrivalState(
        cost_ticks=0,
        uncertain_stops=0,
        detour_miles=0.0,
        stop_count=0,
        predecessor=None,
    )

    for node_index, node in enumerate(nodes[:-1]):
        arrival_states = states[node_index]

        if not any(state is not None for state in arrival_states):
            continue

        departure_states = _build_departure_states(
            node,
            arrival_states,
            capacity_units,
        )

        for edge in graph[node_index]:
            for departure_units in range(
                edge.fuel_units,
                capacity_units + 1,
            ):
                departure_state = departure_states[departure_units]

                if departure_state is None:
                    continue

                arrival_fuel_units = departure_units - edge.fuel_units

                transition = Transition(
                    previous_node_index=(node_index),
                    previous_arrival_fuel_units=(departure_state.arrival_fuel_units),
                    departure_fuel_units=(departure_units),
                    purchased_units=(departure_state.purchased_units),
                    edge_distance_miles=(edge.distance_miles),
                    edge_fuel_units=(edge.fuel_units),
                )

                candidate = ArrivalState(
                    cost_ticks=(departure_state.cost_ticks),
                    uncertain_stops=(departure_state.uncertain_stops),
                    detour_miles=(departure_state.detour_miles),
                    stop_count=(departure_state.stop_count),
                    predecessor=transition,
                )

                existing = states[edge.to_index][arrival_fuel_units]

                if existing is None or _state_key(candidate) < _state_key(existing):
                    states[edge.to_index][arrival_fuel_units] = candidate

    destination_index = len(nodes) - 1

    best = _find_best_destination_state(states[destination_index])

    if best is None:
        raise NoFeasibleFuelPlan(
            "No feasible fuel plan was found " "within the vehicle's range."
        )

    reconstruction = _reconstruct_plan(
        nodes,
        states,
        best["fuel_units"],
    )

    final_state = best["state"]

    estimated_detour_miles = final_state.detour_miles * 2

    return {
        "total_cost": _ticks_to_dollars(final_state.cost_ticks),
        "initial_fuel_gallons": (_units_to_gallons(initial_units)),
        "tank_capacity_gallons": (_units_to_gallons(capacity_units)),
        "total_fuel_purchased_gallons": (
            _units_to_gallons(reconstruction["total_purchased_units"])
        ),
        "fuel_remaining_gallons": (_units_to_gallons(best["fuel_units"])),
        "base_route_distance_miles": (route_distance),
        "estimated_detour_miles": (estimated_detour_miles),
        "estimated_total_distance_miles": (route_distance + estimated_detour_miles),
        "uncertain_stops": (final_state.uncertain_stops),
        "uses_uncertain_stations": (final_state.uncertain_stops > 0),
        "fuel_stops": (reconstruction["fuel_stops"]),
        "travel_legs": (reconstruction["travel_legs"]),
    }
