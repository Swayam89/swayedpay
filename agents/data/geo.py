"""City coordinates, distances and travel facts for Indian trips.

Coordinates for common cities are built in (approximate city centres). Anything else
is looked up once on OpenStreetMap Nominatim (free, no key; cached in memory).
"""

from __future__ import annotations

import math
from functools import lru_cache

import requests

# name -> (lat, lon)
CITIES: dict[str, tuple[float, float]] = {
    "delhi": (28.61, 77.21), "gurugram": (28.46, 77.03), "noida": (28.54, 77.39),
    "mumbai": (19.08, 72.88), "pune": (18.52, 73.86), "bangalore": (12.97, 77.59),
    "chennai": (13.08, 80.27), "hyderabad": (17.39, 78.49), "kolkata": (22.57, 88.36),
    "ahmedabad": (23.02, 72.57), "surat": (21.17, 72.83), "vadodara": (22.31, 73.18),
    "rajkot": (22.30, 70.80), "jaipur": (26.91, 75.79), "udaipur": (24.59, 73.71),
    "jodhpur": (26.24, 73.02), "jaisalmer": (26.92, 70.91), "mount abu": (24.59, 72.71),
    "agra": (27.18, 78.01), "lucknow": (26.85, 80.95), "varanasi": (25.32, 82.97),
    "kanpur": (26.45, 80.33), "rishikesh": (30.09, 78.27), "haridwar": (29.95, 78.16),
    "dehradun": (30.32, 78.03), "mussoorie": (30.46, 78.07), "nainital": (29.38, 79.46),
    "shimla": (31.10, 77.17), "manali": (32.24, 77.19), "dharamshala": (32.22, 76.32),
    "amritsar": (31.63, 74.87), "chandigarh": (30.73, 76.78), "leh": (34.15, 77.58),
    "srinagar": (34.08, 74.80), "goa": (15.50, 73.83), "lonavala": (18.75, 73.41),
    "mahabaleshwar": (17.92, 73.66), "nashik": (20.00, 73.79), "indore": (22.72, 75.86),
    "bhopal": (23.26, 77.41), "nagpur": (21.15, 79.09), "coorg": (12.42, 75.74),
    "mysore": (12.30, 76.64), "ooty": (11.41, 76.70), "kochi": (9.93, 76.27),
    "munnar": (10.09, 77.06), "alleppey": (9.50, 76.34), "trivandrum": (8.52, 76.94),
    "pondicherry": (11.94, 79.81), "madurai": (9.93, 78.12), "hampi": (15.34, 76.46),
    "gokarna": (14.55, 74.32), "visakhapatnam": (17.69, 83.22), "bhubaneswar": (20.30, 85.82),
    "puri": (19.81, 85.83), "darjeeling": (27.04, 88.26), "gangtok": (27.33, 88.61),
    "shillong": (25.58, 91.89), "guwahati": (26.14, 91.74), "patna": (25.59, 85.14),
}

ALIASES = {
    "new delhi": "delhi", "gurgaon": "gurugram", "bengaluru": "bangalore", "bombay": "mumbai",
    "navi mumbai": "mumbai", "calcutta": "kolkata", "madras": "chennai", "mysuru": "mysore",
    "panaji": "goa", "north goa": "goa", "south goa": "goa", "baroda": "vadodara",
    "cochin": "kochi", "thiruvananthapuram": "trivandrum", "puducherry": "pondicherry",
    "alappuzha": "alleppey", "vizag": "visakhapatnam", "madikeri": "coorg", "kodagu": "coorg",
    "benaras": "varanasi", "banaras": "varanasi", "udhagamandalam": "ooty",
}

# City -> (airport city it uses, extra km by road from that airport)
AIRPORT_ACCESS: dict[str, tuple[str, int]] = {
    **{c: (c, 0) for c in (
        "delhi", "mumbai", "pune", "bangalore", "chennai", "hyderabad", "kolkata", "ahmedabad",
        "surat", "vadodara", "rajkot", "jaipur", "udaipur", "jodhpur", "lucknow", "varanasi",
        "dehradun", "amritsar", "chandigarh", "leh", "srinagar", "goa", "indore", "bhopal",
        "nagpur", "kochi", "trivandrum", "madurai", "visakhapatnam", "bhubaneswar", "guwahati",
        "patna", "kanpur", "agra",
    )},
    "gurugram": ("delhi", 15), "noida": ("delhi", 40), "rishikesh": ("dehradun", 35),
    "haridwar": ("dehradun", 50), "mussoorie": ("dehradun", 60), "manali": ("kullu", 50),
    "dharamshala": ("dharamshala", 15), "shimla": ("shimla", 25), "nainital": ("pantnagar", 70),
    "darjeeling": ("bagdogra", 70), "gangtok": ("bagdogra", 125), "shillong": ("guwahati", 120),
    "coorg": ("mysore", 120), "mysore": ("mysore", 10), "ooty": ("coimbatore", 85),
    "munnar": ("kochi", 110), "alleppey": ("kochi", 85), "pondicherry": ("chennai", 150),
    "lonavala": ("pune", 65), "mahabaleshwar": ("pune", 120), "puri": ("bhubaneswar", 60),
    "hampi": ("hubli", 165), "gokarna": ("goa", 150), "mount abu": ("udaipur", 165),
    "jaisalmer": ("jodhpur", 285), "nashik": ("mumbai", 170),
}

# Places no practical passenger train reaches.
NO_TRAIN = {"manali", "leh", "srinagar"}

# Hill towns reached by train to a nearby railhead, then a road transfer: (railhead, km by road).
RAILHEAD: dict[str, tuple[str, int]] = {
    "darjeeling": ("New Jalpaiguri", 70), "gangtok": ("New Jalpaiguri", 115),
    "mussoorie": ("Dehradun", 35), "nainital": ("Kathgodam", 35), "dharamshala": ("Pathankot", 90),
    "coorg": ("Mysore", 120), "munnar": ("Aluva", 110), "ooty": ("Mettupalayam", 50),
    "shillong": ("Guwahati", 100), "mount abu": ("Abu Road", 28), "hampi": ("Hosapete", 13),
}

# Mountain destinations: winding roads, slower and longer than the straight line suggests.
HIGH_HILLS = {"manali", "leh", "shimla", "mussoorie", "nainital", "darjeeling", "gangtok", "dharamshala", "srinagar"}
MILD_HILLS = {"munnar", "ooty", "coorg", "shillong", "rishikesh", "mount abu", "mahabaleshwar"}
HILLS = HIGH_HILLS | MILD_HILLS

# Cost-of-stay tiers: metros and big tourist hubs cost more, small towns less.
PRICEY = {"mumbai", "delhi", "gurugram", "bangalore", "goa", "udaipur", "manali", "leh", "shimla", "gangtok", "chennai", "hyderabad", "pune"}
CHEAP = {"hampi", "gokarna", "puri", "varanasi", "pondicherry", "rishikesh", "haridwar", "alleppey", "mount abu", "jaisalmer", "coorg", "munnar", "ooty"}


def normalise(name: str | None) -> str:
    key = " ".join((name or "").strip().lower().split())
    return ALIASES.get(key, key)


@lru_cache(maxsize=256)
def _geocode(name: str) -> tuple[float, float] | None:
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{name}, India", "format": "json", "limit": 1},
            headers={"User-Agent": "SwayedPay-hackathon/1.0 (https://github.com/Swayam89/swayedpay)"},
            timeout=10,
        )
        data = resp.json() if resp.ok else []
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        return None
    return None


def coords(name: str) -> tuple[float, float] | None:
    key = normalise(name)
    return CITIES.get(key) or _geocode(key)


def nearest_known(point: tuple[float, float]) -> tuple[str, float]:
    """The closest built-in city and its distance, used to borrow facts for unlisted towns."""
    best = min(CITIES, key=lambda c: straight_km(point, CITIES[c]))
    return best, straight_km(point, CITIES[best])


def profile(name: str) -> dict | None:
    """Where a place is and how you get there. Unlisted towns borrow the facts of the
    nearest built-in city (within 150 km), plus the extra road distance to reach them."""
    key = normalise(name)
    point = coords(key)
    if not point:
        return None
    if key in CITIES:
        hub, extra = key, 0.0
    else:
        hub, extra = nearest_known(point)
        if extra > 150:
            hub, extra = "", 0.0
    air = AIRPORT_ACCESS.get(hub) if hub else None
    rail = RAILHEAD.get(hub) if hub else None
    return {
        "key": key,
        "point": point,
        "hub": hub,
        "near": hub if hub and hub != key else "",
        "extra_km": extra,
        "airport": (air[0], air[1] + extra * 1.3) if air else None,
        "train": hub not in NO_TRAIN if hub else True,
        "railhead": (rail[0], rail[1] + extra * 1.3) if rail else ((hub.title(), extra * 1.3) if hub and extra > 20 else None),
        "hills": "high" if hub in HIGH_HILLS else "mild" if hub in MILD_HILLS else "",
        "price_level": 1.3 if hub in PRICEY else 0.8 if hub in CHEAP else 1.0,
    }


def straight_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))
