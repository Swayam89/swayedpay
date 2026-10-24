"""Plan building and the budget check.

The budget check starts from the most comfortable combination and, while the
per-person cost is over budget, swaps whichever component (transport or stay)
saves the most by stepping down one level. Every swap is recorded so the agent
can explain its reasoning in the chat.
"""

from __future__ import annotations

import math

from agents.data.sample_prices import build_route, max_one_way_hours, suggested_nights


def _transport_pp(option: dict, people: int) -> float:
    if "per_person_one_way" in option:
        return 2 * option["per_person_one_way"]
    vehicles = math.ceil(people / option["seats"])
    return 2 * option["per_vehicle_one_way"] * vehicles / people


def _stay_pp(option: dict, people: int, nights: int) -> float:
    if "per_person_per_night" in option:
        return option["per_person_per_night"] * nights
    rooms = math.ceil(people / option["room_size"])
    return option["per_room_per_night"] * rooms * nights / people


def cost(route: dict, t: int, s: int, people: int, nights: int) -> dict:
    days = nights + 1
    breakdown = {
        "transport": round(_transport_pp(route["transport"][t], people)),
        "stay": round(_stay_pp(route["stay"][s], people, nights)),
        "food": route["food_per_person_per_day"] * days,
        "local": route["local_per_person_per_day"] * days,
    }
    per_person = sum(breakdown.values())
    return {
        "transport": route["transport"][t]["name"],
        "travel_hours": round(route["transport"][t]["hours"], 1),
        "stay": route["stay"][s]["name"],
        "breakdown": breakdown,
        "per_person": per_person,
        "total": per_person * people,
    }


def _plan(plan_id: str, name: str, c: dict, budget: int, swaps: list[str] | None = None) -> dict:
    over_by = max(0, c["per_person"] - budget)
    return {
        "id": plan_id,
        "name": name,
        **c,
        "within_budget": over_by == 0,
        "over_by": over_by,
        "swaps": swaps or [],
    }


def budget_fit(route: dict, people: int, nights: int, budget: int) -> tuple[int, int, list[str]]:
    """Step down from the most comfortable combo until it fits (or nothing cheaper exists)."""
    t, s = 0, 0
    swaps: list[str] = []
    current = cost(route, t, s, people, nights)
    while current["per_person"] > budget:
        # Step to the next option down that is actually cheaper (a less comfortable
        # option is not always cheaper, e.g. an overnight bus vs 3AC on long routes).
        moves = []
        for j in range(t + 1, len(route["transport"])):
            c = cost(route, j, s, people, nights)
            if c["per_person"] < current["per_person"]:
                moves.append((("t", j), c))
                break
        for j in range(s + 1, len(route["stay"])):
            c = cost(route, t, j, people, nights)
            if c["per_person"] < current["per_person"]:
                moves.append((("s", j), c))
                break
        if not moves:
            break
        fitting = [m for m in moves if m[1]["per_person"] <= budget]
        if fitting:
            # Something fits: keep as much comfort as possible.
            kind, best = max(fitting, key=lambda m: m[1]["per_person"])
        else:
            # Nothing fits yet: take the biggest saving.
            kind, best = min(moves, key=lambda m: m[1]["per_person"])
        if best["per_person"] >= current["per_person"]:
            break
        saved = current["per_person"] - best["per_person"]
        (which, j) = kind
        if which == "t":
            swaps.append(f"Swapped {current['transport']} → {best['transport']} (saves ₹{saved:,.0f} per person)")
            t = j
        else:
            swaps.append(f"Swapped {current['stay']} → {best['stay']} (saves ₹{saved:,.0f} per person)")
            s = j
        current = best
    return t, s, swaps


def build_plans(origin: str, destination: str, people: int, budget_per_person: int, nights: int | None = None) -> dict:
    """nights=None/0 means the user didn't say; pick a length that suits the distance."""
    if people < 1:
        raise ValueError("people must be at least 1")
    if budget_per_person < 1:
        raise ValueError("budget must be positive")
    route = build_route(origin, destination)
    label = route["data_label"]
    notes = list(route.get("notes") or [])
    nights_assumed = not nights
    nights = max(1, nights or suggested_nights(route))

    # Drop journeys too long for the trip (no 17-hour train on a 1-night trip).
    limit = max_one_way_hours(nights)
    usable = [t for t in route["transport"] if t["hours"] <= limit]
    dropped = [t for t in route["transport"] if t["hours"] > limit]
    if not usable:
        fastest = min(route["transport"], key=lambda t: t["hours"])
        usable = [fastest]
        dropped = [t for t in dropped if t is not fastest]
        notes.append(
            f"Even the fastest option takes about {round(fastest['hours'])}h each way, "
            f"which is a lot for {nights} night{'s' if nights != 1 else ''}. Consider a longer trip."
        )
    if dropped:
        names = ", ".join(f"{t['name']} (~{round(t['hours'])}h)" for t in dropped)
        notes.append(f"Left out options too slow for {nights} night{'s' if nights != 1 else ''}: {names}.")
    route = {**route, "transport": usable}

    t, s, swaps = budget_fit(route, people, nights, budget_per_person)
    fitted = cost(route, t, s, people, nights)
    cheapest = cost(route, len(route["transport"]) - 1, len(route["stay"]) - 1, people, nights)
    # The real cheapest combo is the minimum over all pairs (step order is by comfort, not price).
    for ti in range(len(route["transport"])):
        for si in range(len(route["stay"])):
            c = cost(route, ti, si, people, nights)
            if c["per_person"] < cheapest["per_person"]:
                cheapest = c
    comfort = cost(route, 0, 0, people, nights)

    fits = fitted["per_person"] <= budget_per_person
    plans = [_plan("A", "Best fit for your budget" if fits else "Closest to your budget", fitted, budget_per_person, swaps)]
    seen = {(fitted["transport"], fitted["stay"])}
    for candidate, name in ((cheapest, "Maximum savings"), (comfort, "Most comfortable")):
        key = (candidate["transport"], candidate["stay"])
        if key not in seen:
            seen.add(key)
            plans.append(_plan(chr(ord("A") + len(plans)), name, candidate, budget_per_person))

    return {
        "plans": plans,
        "data_label": label,
        "nights": nights,
        "nights_assumed": nights_assumed,
        "distance_km": route["distance_km"],
        "notes": notes,
    }
