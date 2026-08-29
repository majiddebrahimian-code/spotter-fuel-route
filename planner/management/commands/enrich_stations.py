from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand

from planner.models import FuelStation
from planner.services.exits import fetch_state_exit_candidates
from planner.services.matching import match_station
from planner.services.osm import fetch_state_fuel_candidates


class Command(BaseCommand):
    help = "Enrich unresolved US fuel stations state by state."

    def add_arguments(self, parser):
        parser.add_argument(
            "--state",
            type=str,
            help="Process one state, for example TX.",
        )

        parser.add_argument(
            "--all-states",
            action="store_true",
            help="Process every state with unresolved stations.",
        )

        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum stations to process per state.",
        )

    def handle(self, *args, **options):
        requested_state = options.get("state")
        all_states = options.get("all_states")
        limit = options.get("limit")

        if requested_state and all_states:
            self.stdout.write(self.style.ERROR("Use either --state or --all-states."))
            return

        if not requested_state and not all_states:
            self.stdout.write(self.style.ERROR("Use --state XX or --all-states."))
            return

        # Only stations without coordinates need another matching attempt.
        unresolved = FuelStation.objects.filter(
            latitude__isnull=True,
            longitude__isnull=True,
        ).order_by(
            "state",
            "id",
        )

        if requested_state:
            unresolved = unresolved.filter(state=requested_state.upper())

        stations_by_state = defaultdict(list)

        for station in unresolved.iterator():
            stations_by_state[station.state].append(station)

        if not stations_by_state:
            self.stdout.write(self.style.SUCCESS("No unresolved stations found."))
            return

        total_states = len(stations_by_state)

        total_unresolved = sum(len(stations) for stations in stations_by_state.values())

        total_processed = 0
        total_trusted = 0
        total_uncertain = 0
        total_rejected = 0
        total_errors = 0

        failed_fuel_states = []
        failed_exit_states = []

        self.stdout.write("")
        self.stdout.write("USA Fuel Station Enrichment")
        self.stdout.write("================================")
        self.stdout.write(f"States: {total_states}")
        self.stdout.write(f"Unresolved stations: {total_unresolved}")

        for state_index, (state, state_stations) in enumerate(
            stations_by_state.items(),
            start=1,
        ):
            if limit:
                state_stations = state_stations[:limit]

            self.stdout.write("")
            self.stdout.write("================================")
            self.stdout.write(f"STATE {state_index}/{total_states}: {state}")
            self.stdout.write(f"Stations this run: {len(state_stations)}")

            # --------------------------------
            # PRELOAD FUEL DATA ONCE
            # --------------------------------

            try:
                fuel_data = fetch_state_fuel_candidates(state)

                fuel_object_count = len(fuel_data.get("elements", []))

                self.stdout.write(
                    self.style.SUCCESS(f"Fuel OSM ready: {fuel_object_count}")
                )

            except Exception as exc:
                failed_fuel_states.append(state)

                self.stdout.write(self.style.ERROR("STATE SKIPPED | Fuel OSM failed."))

                self.stdout.write(self.style.ERROR(f"{type(exc).__name__}: {exc}"))

                # Without station POIs matching cannot continue.
                continue

            # --------------------------------
            # PRELOAD EXIT DATA ONCE
            # --------------------------------

            try:
                exit_data = fetch_state_exit_candidates(
                    state,
                    suppress_errors=True,
                )

                exit_object_count = len(exit_data.get("elements", []))

                if exit_object_count:
                    self.stdout.write(
                        self.style.SUCCESS(f"Exit OSM ready: {exit_object_count}")
                    )
                else:
                    failed_exit_states.append(state)

                    self.stdout.write(
                        self.style.WARNING(
                            "Exit OSM unavailable. " "Continuing without exit evidence."
                        )
                    )

            except Exception as exc:
                failed_exit_states.append(state)

                self.stdout.write(
                    self.style.WARNING(
                        "Exit OSM failed. " "Continuing without exit evidence."
                    )
                )

                self.stdout.write(self.style.WARNING(f"{type(exc).__name__}: {exc}"))

            state_processed = 0
            state_trusted = 0
            state_uncertain = 0
            state_rejected = 0
            state_errors = 0

            # --------------------------------
            # LOCAL MATCHING
            # --------------------------------

            for station_index, station in enumerate(
                state_stations,
                start=1,
            ):
                state_processed += 1
                total_processed += 1

                self.stdout.write(
                    f"[{station_index}/{len(state_stations)}] "
                    f"{station.name} | "
                    f"{station.city}, {station.state} | "
                    f"OPIS {station.opis_id}"
                )

                try:
                    result = match_station(station)

                    decision = result.get("decision")
                    best_match = result.get("best_match")
                    margin = result.get("margin")

                    # --------------------------------
                    # TRUSTED
                    # --------------------------------

                    if decision == "trusted":
                        if not best_match:
                            state_rejected += 1
                            total_rejected += 1

                            self.stdout.write(
                                self.style.WARNING("  REJECTED | Missing best match.")
                            )
                            continue

                        station.latitude = best_match["latitude"]
                        station.longitude = best_match["longitude"]
                        station.geocode_status = "approximate"

                        station.match_score = Decimal(str(best_match["final_score"]))

                        if margin is not None:
                            station.match_margin = Decimal(str(margin))

                        station.save(
                            update_fields=[
                                "latitude",
                                "longitude",
                                "geocode_status",
                                "match_score",
                                "match_margin",
                            ]
                        )

                        state_trusted += 1
                        total_trusted += 1

                        self.stdout.write(
                            self.style.SUCCESS(
                                "  TRUSTED | "
                                f"{best_match['matched_name']} | "
                                f"score="
                                f"{best_match['final_score']:.1f} | "
                                f"margin={margin:.1f}"
                            )
                        )

                    # --------------------------------
                    # UNCERTAIN
                    # --------------------------------

                    elif decision == "uncertain":
                        if not best_match:
                            state_rejected += 1
                            total_rejected += 1

                            self.stdout.write(
                                self.style.WARNING(
                                    "  REJECTED | "
                                    "Uncertain result has no best match."
                                )
                            )
                            continue

                        # Keep the candidate coordinates.
                        # Phase 5 can decide whether this station
                        # has enough confidence to participate.
                        station.latitude = best_match["latitude"]
                        station.longitude = best_match["longitude"]
                        station.geocode_status = "uncertain"

                        station.match_score = Decimal(str(best_match["final_score"]))

                        if margin is not None:
                            station.match_margin = Decimal(str(margin))

                        station.save(
                            update_fields=[
                                "latitude",
                                "longitude",
                                "geocode_status",
                                "match_score",
                                "match_margin",
                            ]
                        )

                        state_uncertain += 1
                        total_uncertain += 1

                        self.stdout.write(
                            self.style.WARNING(
                                "  UNCERTAIN SAVED | "
                                f"{best_match['matched_name']} | "
                                f"score="
                                f"{best_match['final_score']:.1f} | "
                                f"margin={margin:.1f}"
                            )
                        )

                    # --------------------------------
                    # REJECTED
                    # --------------------------------

                    else:
                        state_rejected += 1
                        total_rejected += 1

                        reason = result.get(
                            "reason",
                            "No trusted match.",
                        )

                        self.stdout.write(self.style.WARNING(f"  REJECTED | {reason}"))

                except KeyboardInterrupt:
                    self.stdout.write("")
                    self.stdout.write(self.style.WARNING("Enrichment interrupted."))

                    self.stdout.write(
                        "Already saved trusted and uncertain " "stations are preserved."
                    )

                    return

                except Exception as exc:
                    state_errors += 1
                    total_errors += 1

                    self.stdout.write(
                        self.style.ERROR("  ERROR | " f"{type(exc).__name__}: {exc}")
                    )

            self.stdout.write("")
            self.stdout.write(f"{state} SUMMARY")
            self.stdout.write("--------------------------------")
            self.stdout.write(f"Processed: {state_processed}")
            self.stdout.write(f"Trusted:   {state_trusted}")
            self.stdout.write(f"Uncertain: {state_uncertain}")
            self.stdout.write(f"Rejected:  {state_rejected}")
            self.stdout.write(f"Errors:    {state_errors}")

        # --------------------------------
        # FINAL DATABASE COVERAGE
        # --------------------------------

        total_stations = FuelStation.objects.count()

        geocoded = FuelStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
        ).count()

        trusted_coordinates = (
            FuelStation.objects.filter(
                latitude__isnull=False,
                longitude__isnull=False,
            )
            .exclude(geocode_status="uncertain")
            .count()
        )

        uncertain_coordinates = FuelStation.objects.filter(
            geocode_status="uncertain",
            latitude__isnull=False,
            longitude__isnull=False,
        ).count()

        remaining = FuelStation.objects.filter(
            latitude__isnull=True,
            longitude__isnull=True,
        ).count()

        self.stdout.write("")
        self.stdout.write("================================")
        self.stdout.write(self.style.SUCCESS("ENRICHMENT RUN FINISHED"))
        self.stdout.write("================================")

        self.stdout.write(f"Processed this run: {total_processed}")
        self.stdout.write(f"Trusted this run:   {total_trusted}")
        self.stdout.write(f"Uncertain saved:    {total_uncertain}")
        self.stdout.write(f"Rejected:           {total_rejected}")
        self.stdout.write(f"Errors:             {total_errors}")

        self.stdout.write("")
        self.stdout.write("DATABASE COVERAGE")
        self.stdout.write("--------------------------------")

        self.stdout.write(f"Total stations:       {total_stations}")
        self.stdout.write(f"Trusted coordinates:  {trusted_coordinates}")
        self.stdout.write(f"Uncertain coordinates:{uncertain_coordinates}")
        self.stdout.write(f"With coordinates:     {geocoded}")
        self.stdout.write(f"Without coordinates:  {remaining}")

        if total_stations:
            coverage = geocoded / total_stations * 100

            self.stdout.write(f"Coverage:             {coverage:.1f}%")

        self.stdout.write("")

        if failed_fuel_states:
            self.stdout.write(
                self.style.WARNING(
                    "Fuel states failed: " + ", ".join(failed_fuel_states)
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("Fuel states failed: none"))

        if failed_exit_states:
            unique_exit_states = sorted(set(failed_exit_states))

            self.stdout.write(
                self.style.WARNING(
                    "Exit data unavailable: " + ", ".join(unique_exit_states)
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("Exit data unavailable: none"))
