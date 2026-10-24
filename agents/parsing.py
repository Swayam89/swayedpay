"""Rule-based parsers. Used when ASI1 is unavailable, and to fill gaps ASI1 leaves."""

from __future__ import annotations

import json
import re

NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def _to_int(raw: str) -> int | None:
    raw = raw.strip().lower().replace(",", "")
    if raw in NUMBER_WORDS:
        return NUMBER_WORDS[raw]
    multiplier = 1
    if raw.endswith("k"):
        multiplier, raw = 1000, raw[:-1]
    try:
        return int(float(raw) * multiplier)
    except ValueError:
        return None


_NUM = r"(\d[\d,]*(?:\.\d+)?k?|" + "|".join(NUMBER_WORDS) + r")"


def parse_trip(text: str) -> dict:
    """Best-effort extraction of origin, destination, people, budget, nights, date."""
    result: dict = {
        "origin": None, "destination": None, "people": None,
        "budget_per_person": None, "nights": None, "date": None, "members": [],
    }
    lowered = text.lower()

    m = re.search(_NUM + r"\s*(?:of us|people|persons|friends|pax|members|travellers|travelers)", lowered)
    if m:
        result["people"] = _to_int(m.group(1))

    m = re.search(r"(?:₹|rs\.?|inr)\s*" + _NUM, lowered) or re.search(
        _NUM + r"\s*(?:rs|rupees|inr)?\s*(?:each|per person|pp|/person|per head|a head)", lowered
    )
    if m:
        result["budget_per_person"] = _to_int(m.group(1))
        total_hint = re.search(r"total|overall|altogether|in all", lowered)
        if total_hint and result["people"]:
            result["budget_per_person"] = result["budget_per_person"] // result["people"]

    m = re.search(r"from\s+([a-z][a-z ]*?)\s+to\s+([a-z][a-z ]*?)(?=\s*(?:this|next|on|for|,|\.|$|\d|with|under|budget))", lowered)
    if not m:
        m = re.search(r"([a-z]+)\s+to\s+([a-z]+)", lowered)
    if m:
        result["origin"] = m.group(1).strip().title()
        result["destination"] = m.group(2).strip().title()

    m = re.search(_NUM + r"\s*nights?", lowered)
    if m:
        result["nights"] = _to_int(m.group(1))
    else:
        m = re.search(_NUM + r"\s*days?", lowered)
        if m and _to_int(m.group(1)):
            result["nights"] = max(1, _to_int(m.group(1)) - 1)
        elif "weekend" in lowered:
            result["nights"] = 1

    m = re.search(
        r"(this (?:mon|tues|wednes|thurs|fri|satur|sun)day|next (?:mon|tues|wednes|thurs|fri|satur|sun)day|"
        r"this weekend|next weekend|tomorrow|tonight|\d{1,2}(?:st|nd|rd|th)? (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)",
        lowered,
    )
    if m:
        result["date"] = m.group(1)
    return result


def parse_payments(text: str) -> dict:
    """Extract {"members": [...], "payments": {name: amount}} from free text."""
    payments: dict[str, int] = {}
    for m in re.finditer(
        r"([A-Z][a-zA-Z]+)\s+(?:has\s+)?(?:paid|spent|put in|covered|gave)\s*(?:₹|rs\.?|inr)?\s*(\d[\d,]*k?)",
        text,
    ):
        amount = _to_int(m.group(2))
        if amount:
            payments[m.group(1)] = payments.get(m.group(1), 0) + amount

    members: list[str] = []
    stop = {"Plan", "Group", "Members", "We", "Us", "And", "Paid", "The", "I", "Approved", "Ok", "Okay", "Yes"}
    first_clause = re.split(r"[.;\n]", text)[0]
    if "," in first_clause or " and " in first_clause:
        for token in re.findall(r"[A-Z][a-zA-Z]+", first_clause):
            if token not in stop and token not in members:
                members.append(token)
    for name in payments:
        if name not in members:
            members.append(name)
    return {"members": members, "payments": payments}


_PLAN_PATTERNS = [
    re.compile(r"plan[_\s-]?id[\s:=\"']*([abc])\b", re.IGNORECASE),
    re.compile(r"\b(?:plan|option)\s*([abc])\b", re.IGNORECASE),
    re.compile(r"^\s*([abc])\s*[.!]?\s*$", re.IGNORECASE),
]


def parse_card_selection(text: str) -> dict | None:
    """Card taps arrive as JSON (direct @mention) or as prose (via the ASI:One planner)."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                selection = {k: str(v) for k, v in data.items() if k in ("action", "plan_id")}
                if selection:
                    if "plan_id" in selection:
                        selection["plan_id"] = selection["plan_id"].upper()
                    return selection
        except json.JSONDecodeError:
            pass
    if re.search(r"new[_\s-]?trip|start over|reset", stripped, re.IGNORECASE):
        return {"action": "new_trip"}
    for pattern in _PLAN_PATTERNS:
        m = pattern.search(stripped)
        if m:
            return {"action": "choose_plan", "plan_id": m.group(1).upper()}
    return None


def merge_trip(base: dict, update: dict | None) -> dict:
    """Keep known values, fill missing ones from `update`."""
    merged = dict(base)
    for key, value in (update or {}).items():
        if value in (None, "", []):
            continue
        if key in ("people", "budget_per_person", "nights"):
            value = _to_int(str(value)) if not isinstance(value, int) else value
            if not value or value <= 0:
                continue
        merged[key] = value
    return merged


REQUIRED_TRIP_FIELDS = {
    "origin": "where you're leaving from",
    "destination": "where you're going",
    "people": "how many people are going",
    "budget_per_person": "the budget per person",
}


def missing_fields(trip: dict) -> list[str]:
    return [label for key, label in REQUIRED_TRIP_FIELDS.items() if not trip.get(key)]
