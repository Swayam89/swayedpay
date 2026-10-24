"""'Book it yourself' handoff links for a chosen plan.

SwayedPay doesn't book anything. These links take the organiser to the official or
well-known place to book each part of the plan. Every URL pattern here was checked
to load: IRCTC train search, redBus, Google Flights search and Google Maps URLs.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode


def _maps_search(query: str) -> str:
    return "https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": query})


def links_for(plan: dict, trip: dict) -> list[tuple[str, str]]:
    origin, destination = trip.get("origin", ""), trip.get("destination", "")
    transport = plan.get("transport", "")
    links: list[tuple[str, str]] = []
    if transport.startswith("Flight"):
        q = quote(f"Flights from {origin} to {destination}")
        links.append(("Flights on Google Flights", f"https://www.google.com/travel/flights?q={q}"))
    elif transport.startswith("Train"):
        links.append(("Train tickets on IRCTC", "https://www.irctc.co.in/nget/train-search"))
    elif "bus" in transport.lower():
        links.append(("Bus tickets on redBus", "https://www.redbus.in/"))
    elif "cab" in transport.lower():
        links.append(("Driving route on Google Maps", "https://www.google.com/maps/dir/?" + urlencode(
            {"api": "1", "origin": origin, "destination": destination, "travelmode": "driving"})))
        links.append(("Outstation cabs near you", _maps_search(f"outstation cab service in {origin}")))
    if "road from" in transport:
        links.append(("Onward road transfer", "https://www.google.com/maps/dir/?" + urlencode(
            {"api": "1", "destination": destination, "travelmode": "driving"})))

    stay = plan.get("stay", "")
    stay_query = {"Hostel dorm": "hostels", "Budget hotel": "budget hotels", "Mid-range hotel": "hotels"}.get(stay, "hotels")
    links.append((f"{stay_query.capitalize()} in {destination}", _maps_search(f"{stay_query} in {destination}")))
    return links


def links_markdown(plan: dict, trip: dict) -> str:
    items = " · ".join(f"[{label}]({url})" for label, url in links_for(plan, trip))
    return f"**Book it yourself:** {items}\n_SwayedPay doesn't book or take payments; these open the booking sites._"
