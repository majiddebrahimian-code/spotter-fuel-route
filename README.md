# Fuel Route Planner

A Django-based route planning API that calculates a driving route between two locations in the United States and finds cost-effective fuel stops along the way.

The application uses the fuel price data supplied with the assessment, OpenStreetMap-based services for geocoding and routing, and a Dynamic Programming optimizer to determine where and how much fuel should be purchased during the trip.

It also includes an interactive map for visualizing the route and the selected fuel stops.

---

## Features

- Route planning between two US locations
- Fuel stop optimization based on supplied fuel prices
- Vehicle range constraint of 500 miles
- Fuel consumption assumption of 10 MPG
- Dynamic Programming based fuel optimization
- Fuel purchase quantity optimization
- Detour-aware fuel consumption
- Interactive Leaflet / OpenStreetMap route map
- Fuel stop markers with purchase details
- PostgreSQL-backed fuel station database
- API validation and error handling
- Automated optimizer tests

---

## Tech Stack

- Python 3.13
- Django 6.1
- Django REST Framework
- PostgreSQL
- Docker
- OpenStreetMap
- Nominatim
- OSRM
- Leaflet
- JavaScript
- HTML / CSS

---

## How It Works

The main request flow is:

```text
Start + Finish
      |
      v
Geocoding
      |
      v
OSRM Route
      |
      v
Fuel Station Candidate Selection
      |
      v
Dynamic Programming Optimizer
      |
      v
Optimal Fuel Stops
      |
      v
JSON API Response
      |
      v
Leaflet Map
```

The start and finish locations are first geocoded inside the United States.

OSRM is then used to calculate the driving route.

The returned route geometry is used to locate relevant fuel stations and determine their approximate position and detour from the route.

The optimizer then decides:

- Which fuel stations should be used
- How much fuel should be purchased at each stop
- How to minimize total fuel cost while respecting the vehicle range

The same GeoJSON route returned by the backend is also used by the Leaflet interface, so the frontend does not need to make another routing request.

---

## Vehicle Assumptions

The assessment specifies:

```text
Fuel economy: 10 MPG
Maximum range: 500 miles
```

From those values:

```text
Tank capacity: 50 gallons
```

The implementation assumes the vehicle starts with a full tank:

```text
Initial fuel: 50 gallons
```

The cost of the initial tank is not included in the calculated fuel cost because no starting fuel price is provided by the assessment.

---

## Fuel Optimization

The fuel optimization problem is solved using Dynamic Programming rather than a simple greedy strategy.

Fuel is represented internally in 0.1 gallon increments.

With a 50-gallon tank, this produces 501 possible fuel states:

```text
0.0 gallons
0.1 gallons
0.2 gallons
...
50.0 gallons
```

For each candidate station, the optimizer considers:

- Fuel available on arrival
- Fuel required for the next leg
- Station fuel price
- Amount of fuel to purchase
- Tank capacity
- Detour fuel consumption
- Remaining fuel at the destination

The primary objective is:

```text
Minimize total fuel cost
```

When two plans have exactly the same fuel cost, the optimizer uses additional tie-breakers:

1. Prefer fewer uncertain station matches
2. Prefer lower estimated detour distance
3. Prefer less remaining fuel at the destination
4. Prefer fewer fuel stops

This allows the optimizer to consider future fuel prices instead of simply selecting the cheapest currently reachable station.

---

## Example Request

```http
POST /api/routes/
Content-Type: application/json
```

```json
{
  "start": "New York, NY",
  "finish": "Miami, FL"
}
```

Example result from development testing:

```text
Route distance: ~1279 miles
Fuel stops: 3
Fuel purchased: ~78.2 gallons
Estimated fuel cost: ~$226.97
Estimated detour: ~1.23 miles
Fuel remaining at destination: 0 gallons
```

The response also contains the full route geometry and detailed information about every selected fuel stop.

---

## API Response

The API returns the following main sections:

```json
{
  "start": {},
  "finish": {},
  "route": {},
  "vehicle": {},
  "fuel_plan": {}
}
```

### Start and Finish

Contain the resolved location name and coordinates.

### Route

Contains:

- Distance in miles
- Estimated duration in minutes
- GeoJSON route geometry

### Vehicle

Contains:

- MPG
- Maximum range
- Tank capacity
- Initial fuel

### Fuel Plan

Contains:

- Total fuel cost
- Total fuel purchased
- Remaining fuel at destination
- Base route distance
- Estimated detour
- Estimated total distance
- Number of uncertain stops
- Selected fuel stops
- Travel legs

Each selected fuel stop contains information such as:

- Station name
- OPIS ID
- Address
- City
- State
- Coordinates
- Fuel price
- Route position
- Estimated detour
- Fuel on arrival
- Gallons purchased
- Fuel on departure
- Stop cost
- Geocoding confidence metadata

---

## Fuel Price Data

Fuel prices come directly from the dataset supplied with the assessment.

The source file contains fields including:

```text
OPIS Truckstop ID
Truckstop Name
Address
City
State
Rack ID
Retail Price
```

The original fuel price observations are preserved in the database rather than being overwritten during import.

Some stations contain multiple fuel price observations.

For optimization, the application uses the median of the available price observations for a station as its representative fuel price.

This keeps the raw source data intact while providing one stable value for route optimization.

---

## Fuel Station Geocoding

The supplied fuel dataset contains station names, addresses and fuel prices, but does not contain latitude and longitude coordinates.

Because geographic coordinates are required to determine whether a station is useful for a route, a preprocessing pipeline was built to enrich the station records.

The enrichment process uses OpenStreetMap data and local candidate matching.

Station information such as the following is used during matching:

- Station name
- Address
- City
- State
- POI type
- Geographic context

Candidate matches are assigned confidence metadata and classified into categories such as:

```text
exact
approximate
uncertain
failed
```

The matching score is a heuristic similarity score and should not be interpreted as a statistical probability.

After enrichment, the dataset contained approximately:

```text
Total stations:        6626
Trusted coordinates:   2523
Uncertain coordinates: 1668
Usable coordinates:    4191
Coverage:               63.3%
```

Both trusted and uncertain stations can be considered by the optimizer.

However, if two complete fuel plans have exactly the same monetary cost, the plan containing fewer uncertain stations is preferred.

---

## Route and Station Processing

The route returned by OSRM contains detailed GeoJSON geometry.

Fuel stations with usable coordinates are projected onto this route.

For each station, the application calculates approximately:

```text
route_mile
detour_miles
```

`route_mile` represents where the station occurs along the trip.

`detour_miles` represents the estimated one-way distance between the route and the station.

The base route distance is scaled to remain consistent with the official distance returned by OSRM.

---

## Detour Handling

Fuel station detours affect fuel consumption.

For two selected points `i` and `j`, the estimated travel distance includes:

```text
detour from i
+ forward route distance
+ detour to j
```

This means a station that is slightly farther away from the route may still be selected if its cheaper fuel price compensates for the additional fuel required for the detour.

The implementation intentionally does not make a separate OSRM request for every fuel station.

Doing that for hundreds or thousands of stations would make the API unnecessarily slow and would generate a large number of external routing requests.

Instead, station detours are estimated geometrically as a practical assessment trade-off.

---

## Candidate Reduction

Running Dynamic Programming over every geocoded station would create unnecessary computational cost for long routes.

Before optimization, the application therefore reduces the station set.

Stations are:

1. Projected onto the route
2. Assigned a route-mile position
3. Assigned an estimated detour
4. Grouped into route-distance buckets
5. Reduced using useful price/detour candidates

Candidate selection considers stations such as:

- Cheapest station in the area
- Closest station to the route
- Cheapest trusted station
- Useful price/detour trade-offs

The Dynamic Programming optimizer then operates on the resulting shortlist.

This dramatically reduces execution time while preserving practical fuel choices.

---

## Performance

A long-distance route from New York to Miami was used during development as a performance benchmark.

The initial implementation processed a much larger station search space.

Initial performance was approximately:

```text
Station preparation: ~100 seconds
Fuel optimization:   ~191 seconds
Total:               ~295 seconds
```

Route projection and station candidate selection were then optimized.

Final benchmark was approximately:

```text
Start geocoding:     ~1.0 second
Finish geocoding:    ~0.7 second
OSRM routing:        ~1.3 seconds
Station preparation: ~3.5 seconds
Fuel optimization:   ~5.5 seconds
Total:               ~12 seconds
```

The route was approximately:

```text
1279 miles
```

The optimized result remained effectively the same in fuel cost while reducing execution time from roughly five minutes to around twelve seconds.

External geocoding and routing response times are included in this benchmark.

---

## Interactive Map

An interactive route visualization is available at:

```text
/map/
```

The map uses:

- Leaflet
- OpenStreetMap tiles
- GeoJSON returned by the route planning API

It displays:

- Start location
- Destination
- Driving route
- Selected fuel stops
- Fuel price
- Fuel on arrival
- Fuel purchased
- Fuel on departure
- Cost at each stop
- Estimated station detour
- Total fuel cost
- Total fuel purchased
- Remaining fuel at destination
- Route distance
- Estimated driving time

The frontend uses the route geometry already returned by the backend and does not request the route from OSRM again.

---

## Error Handling

The API validates input and returns appropriate HTTP status codes.

### Missing or Invalid Input

```text
400 Bad Request
```

Example:

```json
{
  "finish": [
    "This field is required."
  ]
}
```

### Location Not Found

```text
400 Bad Request
```

Example:

```json
{
  "error": "Start location could not be found in the USA."
}
```

### No Feasible Fuel Plan

```text
422 Unprocessable Entity
```

This can occur when the vehicle cannot reach a valid next fuel station within its maximum range.

### External Mapping Service Failure

```text
502 Bad Gateway
```

External geocoding or routing failures are handled without exposing internal server errors to the API client.

---

## Project Structure

```text
spotter-fuel-route/
│
├── config/
│
├── planner/
│   ├── management/
│   ├── migrations/
│   ├── services/
│   │   ├── corridor.py
│   │   ├── geocoding.py
│   │   ├── optimizer.py
│   │   ├── route_planner.py
│   │   ├── routing.py
│   │   └── station_data.py
│   │
│   ├── templates/
│   │   └── planner/
│   │       └── map.html
│   │
│   ├── models.py
│   ├── serializers.py
│   ├── urls.py
│   └── views.py
│
├── docker-compose.yml
├── manage.py
├── requirements.txt
└── README.md
```

---

## Running the Project

### 1. Clone the Repository

```bash
git clone <repository-url>
cd spotter-fuel-route
```

### 2. Create a Virtual Environment

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Start PostgreSQL

```bash
docker compose up -d
```

### 5. Run Database Migrations

```bash
python manage.py migrate
```

### 6. Import Fuel Data

Import the fuel price file supplied with the assessment using the project's fuel import management command.

The enrichment process can then be used to resolve geographic coordinates for fuel stations.

### 7. Start Django

```bash
python manage.py runserver
```

The API will be available at:

```text
http://127.0.0.1:8000/api/routes/
```

The interactive map will be available at:

```text
http://127.0.0.1:8000/map/
```

---

## Testing

The optimizer includes automated tests covering scenarios such as:

- Route shorter than 500 miles
- Route exactly at the 500-mile range
- Routes requiring fuel stops
- Impossible fuel gaps
- Expensive station before cheaper station
- Cheap station before expensive station
- Trusted vs uncertain station tie-breaking
- Stations more than five miles away from the route
- Detour fuel consumption
- Zero-purchase station handling
- Fractional fuel prices
- Fuel consumption rounding
- Destination fuel handling
- Maximum leg range
- Forward station ordering

Run optimizer tests with:

```bash
python manage.py test planner.test_optimizer
```

Run the complete Django test suite with:

```bash
python manage.py test
```

---

## Design Decisions and Assumptions

### Full Initial Tank

The vehicle starts with a full 50-gallon tank.

The initial fuel is not charged as part of the trip cost because the assessment does not provide a starting fuel price.

### Fixed Driving Route

The application optimizes fuel stops for the route returned by OSRM.

It intentionally keeps route selection separate from fuel optimization.

The routing service contains support for retrieving route alternatives as a possible extension, but alternative-route optimization is not part of the main assessment execution path.

### Fuel Purchases

The optimizer does not automatically fill the tank at every station.

It calculates how much fuel should be purchased based on:

- Current fuel
- Reachable future stations
- Fuel prices
- Tank capacity
- Detour consumption

### Destination

The destination is not treated as a fuel station.

The optimizer avoids purchasing unnecessary fuel and therefore prefers to arrive with as little unused fuel as practical.

### Representative Station Price

When multiple price observations exist for the same station, their median is used as the representative optimization price.

Raw observations remain stored separately.

---

## Known Limitations

This implementation intentionally makes several practical trade-offs suitable for the assessment.

- Public Nominatim and OSRM services may have availability or rate limits.
- Not every station in the supplied dataset can be confidently geocoded.
- Station detours are geometric estimates rather than exact road detours.
- Candidate compression is used before Dynamic Programming for performance.
- City-level input is geocoded to a representative location rather than an exact street address.
- Fuel prices come from the supplied assessment dataset and are not fetched from a real-time fuel-price service.
- The application optimizes fuel stops for the selected OSRM route rather than choosing an entirely different route based on fuel prices.

---

## Possible Improvements

With production infrastructure, the system could be extended with:

- Commercial geocoding and routing providers
- Exact road-distance calculations for station detours
- Geocoding cache
- Route result cache
- Real-time fuel prices
- Alternative-route fuel cost comparison
- Exact address input
- Latitude / longitude input
- Background fuel station enrichment
- Geographic database indexing
- Production-ready map tile provider

---

## Why Dynamic Programming?

A simple greedy strategy such as always choosing the cheapest reachable station is not sufficient for this problem.

The best decision at one station depends on what happens later in the trip.

For example, the optimizer may choose to:

- Buy only enough fuel to reach a cheaper station
- Buy additional fuel at a cheap station to avoid buying more at an expensive station
- Avoid a cheap station if its detour consumes too much fuel
- Select an uncertain station when it produces a genuinely cheaper complete plan
- Prefer a trusted station when the complete monetary cost is exactly equal

Dynamic Programming allows these decisions to be evaluated together while respecting fuel capacity and vehicle range.

---

## Summary

This project combines:

```text
Django REST API
+ PostgreSQL
+ OpenStreetMap geocoding
+ OSRM routing
+ Fuel station data enrichment
+ Dynamic Programming
+ Performance optimization
+ Leaflet route visualization
```

The result is an end-to-end fuel route planner that returns the driving route, optimized fuel stops, fuel purchase quantities, estimated total fuel cost, remaining fuel, travel legs, and an interactive route map.