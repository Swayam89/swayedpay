"""SAMPLE price data for the hackathon demo.

These are rough, hand-written estimates in rupees, NOT live fares or hotel rates.
Every reply that uses them says so. Transport and stay options are listed from most
to least comfortable; the planner relies on that order when it swaps options.
"""

SAMPLE_LABEL = "Sample estimates for the demo, not live prices"
GENERIC_LABEL = "Rough generic estimates (this route has no sample data), not live prices"

CITY_ALIASES = {
    "new delhi": "delhi", "gurugram": "delhi", "gurgaon": "delhi", "noida": "delhi",
    "bengaluru": "bangalore", "bombay": "mumbai", "navi mumbai": "mumbai",
}

_DELHI_HOTELS = [
    {"name": "3-star hotel", "per_room_per_night": 3200, "room_size": 2},
    {"name": "Budget hotel", "per_room_per_night": 1800, "room_size": 2},
    {"name": "Hostel dorm", "per_person_per_night": 600},
]

ROUTES: dict[tuple[str, str], dict] = {
    ("delhi", "jaipur"): {
        "transport": [
            {"name": "Private cab (SUV)", "per_vehicle_one_way": 6000, "seats": 6},
            {"name": "Train (chair car)", "per_person_one_way": 650},
            {"name": "Volvo bus", "per_person_one_way": 550},
        ],
        "stay": _DELHI_HOTELS,
        "food_per_person_per_day": 600,
        "local_per_person_per_day": 300,
    },
    ("delhi", "agra"): {
        "transport": [
            {"name": "Private cab (SUV)", "per_vehicle_one_way": 5000, "seats": 6},
            {"name": "Train (Gatimaan, chair car)", "per_person_one_way": 800},
            {"name": "Volvo bus", "per_person_one_way": 450},
        ],
        "stay": _DELHI_HOTELS,
        "food_per_person_per_day": 550,
        "local_per_person_per_day": 400,
    },
    ("delhi", "rishikesh"): {
        "transport": [
            {"name": "Private cab (SUV)", "per_vehicle_one_way": 7000, "seats": 6},
            {"name": "Train + shared taxi", "per_person_one_way": 700},
            {"name": "Volvo bus", "per_person_one_way": 750},
        ],
        "stay": [
            {"name": "Riverside camp", "per_person_per_night": 1500},
            {"name": "Budget hotel", "per_room_per_night": 1600, "room_size": 2},
            {"name": "Hostel dorm", "per_person_per_night": 500},
        ],
        "food_per_person_per_day": 500,
        "local_per_person_per_day": 300,
    },
    ("delhi", "manali"): {
        "transport": [
            {"name": "Private tempo traveller", "per_vehicle_one_way": 18000, "seats": 12},
            {"name": "Volvo sleeper bus", "per_person_one_way": 1500},
            {"name": "Ordinary bus", "per_person_one_way": 900},
        ],
        "stay": [
            {"name": "Mountain-view hotel", "per_room_per_night": 3000, "room_size": 2},
            {"name": "Homestay", "per_room_per_night": 1800, "room_size": 2},
            {"name": "Hostel dorm", "per_person_per_night": 600},
        ],
        "food_per_person_per_day": 600,
        "local_per_person_per_day": 500,
    },
    ("mumbai", "goa"): {
        "transport": [
            {"name": "Flight (economy)", "per_person_one_way": 4000},
            {"name": "Train (3AC)", "per_person_one_way": 1500},
            {"name": "Sleeper bus", "per_person_one_way": 1100},
        ],
        "stay": [
            {"name": "Beach resort", "per_room_per_night": 4500, "room_size": 2},
            {"name": "Guesthouse", "per_room_per_night": 2000, "room_size": 2},
            {"name": "Hostel dorm", "per_person_per_night": 700},
        ],
        "food_per_person_per_day": 800,
        "local_per_person_per_day": 500,
    },
    ("mumbai", "lonavala"): {
        "transport": [
            {"name": "Private cab (SUV)", "per_vehicle_one_way": 3500, "seats": 6},
            {"name": "Train (second class)", "per_person_one_way": 150},
        ],
        "stay": [
            {"name": "Villa with pool", "per_room_per_night": 4000, "room_size": 3},
            {"name": "Budget hotel", "per_room_per_night": 1800, "room_size": 2},
        ],
        "food_per_person_per_day": 600,
        "local_per_person_per_day": 300,
    },
    ("bangalore", "coorg"): {
        "transport": [
            {"name": "Private cab (SUV)", "per_vehicle_one_way": 7500, "seats": 6},
            {"name": "KSRTC Volvo bus", "per_person_one_way": 700},
        ],
        "stay": [
            {"name": "Coffee-estate homestay", "per_room_per_night": 3500, "room_size": 2},
            {"name": "Budget homestay", "per_room_per_night": 1800, "room_size": 2},
        ],
        "food_per_person_per_day": 600,
        "local_per_person_per_day": 400,
    },
    ("bangalore", "mysore"): {
        "transport": [
            {"name": "Private cab (sedan)", "per_vehicle_one_way": 3000, "seats": 4},
            {"name": "Train (chair car)", "per_person_one_way": 300},
            {"name": "KSRTC bus", "per_person_one_way": 250},
        ],
        "stay": [
            {"name": "Heritage hotel", "per_room_per_night": 3500, "room_size": 2},
            {"name": "Budget hotel", "per_room_per_night": 1500, "room_size": 2},
        ],
        "food_per_person_per_day": 500,
        "local_per_person_per_day": 300,
    },
}

GENERIC_ROUTE = {
    "transport": [
        {"name": "Private cab", "per_vehicle_one_way": 7000, "seats": 6},
        {"name": "Train", "per_person_one_way": 900},
        {"name": "Bus", "per_person_one_way": 700},
    ],
    "stay": [
        {"name": "Mid-range hotel", "per_room_per_night": 3000, "room_size": 2},
        {"name": "Budget hotel", "per_room_per_night": 1600, "room_size": 2},
        {"name": "Hostel dorm", "per_person_per_night": 600},
    ],
    "food_per_person_per_day": 600,
    "local_per_person_per_day": 400,
}


def normalise_city(name: str | None) -> str:
    key = (name or "").strip().lower()
    return CITY_ALIASES.get(key, key)


def get_route(origin: str, destination: str) -> tuple[dict, str]:
    """Return (route data, label). Routes work in both directions."""
    a, b = normalise_city(origin), normalise_city(destination)
    route = ROUTES.get((a, b)) or ROUTES.get((b, a))
    if route:
        return route, SAMPLE_LABEL
    return GENERIC_ROUTE, GENERIC_LABEL
