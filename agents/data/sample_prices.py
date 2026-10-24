"""Distance-based price ESTIMATES for any pair of places in India.

These are not live fares. Every reply that uses them says so. The rules aim to be
realistic rather than exact:

- Road distance = straight line x 1.25, plus a winding-road allowance into the hills.
  Drive time uses plains speed, with the last stretch into the hills much slower.
- Rail distance = straight line x 1.15. Hill towns without a station are reached by
  train to the nearest railhead (New Jalpaiguri for Darjeeling, Kathgodam for
  Nainital...) plus a road transfer. Manali, Leh and Srinagar get no train option.
- Flights only for 400+ km when both places have an airport within reach; the fare
  includes the road transfer from each airport.
- A private cab only up to 700 km by road; buses up to 1,500 km.
- Unlisted towns borrow the facts of the nearest built-in city (Kasol -> Manali).
- Hotels, food and local transport cost more in metros and tourist hubs.

Transport and stay options are ordered from most to least comfortable; the planner's
budget check relies on that order when it swaps options.
"""

from __future__ import annotations

import math

from agents.data import geo

ESTIMATE_LABEL = "Estimated from distance, not live fares or hotel rates"

PLAINS_KMH = 55.0
HILL_KMH = 28.0
# Roughly how much of a drive into the hills is on slow mountain roads.
HILL_STRETCH_KM = {"high": 150.0, "mild": 60.0, "": 0.0}


class RouteError(ValueError):
    pass


def _drive(straight: float, hills: str) -> tuple[float, float]:
    """(road km, hours) for a road trip."""
    stretch = HILL_STRETCH_KM[hills]
    road = straight * 1.25 + stretch * 0.25
    hill = min(road, stretch)
    return road, (road - hill) / PLAINS_KMH + hill / HILL_KMH


def build_route(origin: str, destination: str) -> dict:
    a, b = geo.profile(origin), geo.profile(destination)
    if not a:
        raise RouteError(f"I couldn't find '{origin}' on the map. Could you give a nearby bigger city?")
    if not b:
        raise RouteError(f"I couldn't find '{destination}' on the map. Could you give a nearby bigger city?")
    straight = geo.straight_km(a["point"], b["point"])
    if straight < 40:
        raise RouteError(f"{origin} and {destination} are very close; I plan trips between cities.")

    hills = "high" if "high" in (a["hills"], b["hills"]) else ("mild" if (a["hills"] or b["hills"]) else "")
    road, drive_hours = _drive(straight, hills)
    transport: list[dict] = []

    # Flight (fare includes a cab from/to each airport).
    if straight >= 400 and a["airport"] and b["airport"] and a["airport"][0] != b["airport"][0]:
        transfer_km = a["airport"][1] + b["airport"][1]
        fare = 2200 + 3.2 * straight + 12 * transfer_km
        hours = 1 + straight / 700 + 2.5 + transfer_km / 35
        via = f" via {b['airport'][0].title()} airport" if b["airport"][1] > 20 else ""
        transport.append({"name": f"Flight (economy){via}", "kind": "flight", "per_person_one_way": round(fare, -1), "hours": hours})

    # Private cab for shorter road trips.
    if road <= 700:
        days_driving = max(1, math.ceil(drive_hours / 10))
        transport.append({
            "name": "Private cab (SUV)", "kind": "cab",
            "per_vehicle_one_way": round(18 * road + 400 * days_driving, -1), "seats": 6, "hours": drive_hours,
        })

    # Train, possibly to a railhead plus a road transfer at either end.
    if a["train"] and b["train"]:
        transfer_km = sum(p["railhead"][1] for p in (a, b) if p["railhead"])
        rail_km = max(80.0, straight * 1.15 - transfer_km * 0.5)
        if rail_km >= 100:
            rail_kmh = 65.0 if rail_km > 800 else 55.0
            hours = rail_km / rail_kmh + transfer_km / 30
            transfer_cost = 4 * transfer_km  # shared taxi / bus share per person
            heads = [p["railhead"][0] for p in (a, b) if p["railhead"]]
            suffix = f" + road from {' / '.join(heads)}" if heads else ""
            transport.append({"name": f"Train (3AC){suffix}", "kind": "train3ac",
                              "per_person_one_way": round(1.6 * rail_km + 100 + transfer_cost, -1), "hours": hours})
            transport.append({"name": f"Train (sleeper){suffix}", "kind": "trainsl",
                              "per_person_one_way": round(0.55 * rail_km + 50 + transfer_cost, -1), "hours": hours})

    # Bus.
    if road <= 1500:
        transport.append({
            "name": "AC sleeper bus" if drive_hours > 7 else "AC bus", "kind": "bus",
            "per_person_one_way": round(max(300, 1.8 * road + 50), -1), "hours": drive_hours * 1.1,
        })

    if not transport:
        raise RouteError(
            f"I can't find a sensible way from {origin} to {destination} (about {round(road):,} km). "
            "Try a nearby bigger city."
        )

    rank = {"flight": 0, "cab": 1, "train3ac": 2, "bus": 3, "trainsl": 4}
    transport.sort(key=lambda t: rank[t["kind"]])

    level = b["price_level"]
    stay = [
        {"name": "Mid-range hotel", "per_room_per_night": round(3200 * level, -1), "room_size": 2},
        {"name": "Budget hotel", "per_room_per_night": round(1800 * level, -1), "room_size": 2},
        {"name": "Hostel dorm", "per_person_per_night": round(600 * level, -1)},
    ]
    notes = [f"{p_name} is near {p['near'].title()}" for p_name, p in ((origin, a), (destination, b)) if p["near"]]
    return {
        "transport": transport,
        "stay": stay,
        "food_per_person_per_day": round(600 * level, -1),
        "local_per_person_per_day": round(300 * level, -1),
        "distance_km": round(road),
        "data_label": ESTIMATE_LABEL,
        "notes": notes,
    }


def suggested_nights(route: dict) -> int:
    """Trip length that suits the journey, based on the fastest ground option
    (a flight may not fit the budget, so it shouldn't decide the trip length)."""
    ground = [t["hours"] for t in route["transport"] if t["kind"] != "flight"]
    fastest = min(ground) if ground else min(t["hours"] for t in route["transport"])
    if fastest <= 8:
        return 1
    if fastest <= 14:
        return 2
    if fastest <= 24:
        return 3
    return 4


def max_one_way_hours(nights: int) -> float:
    """Longest sensible one-way journey for a trip of this length."""
    return max(12.0, 8.0 * nights)
