"""Rule-based parsers. Used when ASI1 is unavailable, and to fill gaps ASI1 leaves.

SwayedPay never guesses: anything these parsers can't read with confidence stays
empty, and the orchestrator asks the user for it.
"""

from __future__ import annotations

import json
import re

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def to_int(raw: str) -> int | None:
    raw = str(raw).strip().lower().replace(",", "").replace("₹", "")
    if raw in NUMBER_WORDS:
        return NUMBER_WORDS[raw]
    multiplier = 1
    if raw.endswith("lakh") or raw.endswith("lac"):
        multiplier, raw = 100000, re.sub(r"\s*(lakh|lac)$", "", raw)
    elif raw.endswith("k"):
        multiplier, raw = 1000, raw[:-1]
    try:
        return int(float(raw) * multiplier)
    except ValueError:
        return None


_NUM = r"(\d[\d,]*(?:\.\d+)?\s*(?:k|lakh|lac)?|" + "|".join(NUMBER_WORDS) + r")"
_PER_PERSON = re.compile(r"\beach\b|per[\s-]?person|per head|a head|\bpp\b|/person|per pax|apiece", re.IGNORECASE)
_TOTAL = re.compile(
    r"\btotal\b|overall|altogether|in all|for (?:all of us|all|everyone|the group|the whole group|us all)|group budget|combined",
    re.IGNORECASE,
)


def budget_basis(text: str) -> str | None:
    if _PER_PERSON.search(text):
        return "per_person"
    if _TOTAL.search(text):
        return "total"
    return None


def parse_trip(text: str) -> dict:
    """Best-effort extraction. Fields stay None unless the text clearly states them."""
    result: dict = {
        "origin": None, "destination": None, "people": None, "budget_amount": None,
        "budget_basis": None, "nights": None, "date": None, "members": [],
    }
    lowered = text.lower()

    m = re.search(_NUM + r"\s*(?:of us|people|persons|friends|pax|members|travellers|travelers|adults)", lowered)
    if m:
        result["people"] = to_int(m.group(1))
    # "with 4 friends" could mean 4 people or 4 friends plus the user: don't guess.
    ambiguous = re.search(r"\bwith\s+" + _NUM + r"\s*(?:friends|others|buddies|mates|colleagues)", lowered)
    explicit = re.search(_NUM + r"\s*(?:of us|people in total|in total|people total|total people)", lowered)
    if ambiguous and not explicit:
        result["people"] = None
        result["people_hint"] = to_int(ambiguous.group(1))

    m = (
        re.search(r"(?:₹|rs\.?|inr)\s*" + _NUM, lowered)
        or re.search(_NUM + r"\s*(?:rs\b|rupees|inr)", lowered)
        or re.search(r"budget\s*(?:of|is|:|=)?\s*(?:₹|rs\.?|inr)?\s*" + _NUM, lowered)
        or re.search(_NUM + r"\s*(?:each|per person|per head|pp\b|/person|total|overall|in total|for (?:the group|all))", lowered)
        or re.search(r"(\d[\d,]*(?:\.\d+)?\s*(?:k|lakh|lac))\b", lowered)  # "40k", "1.5 lakh" are money
    )
    if m:
        result["budget_amount"] = to_int(m.group(1))
    result["budget_basis"] = budget_basis(text)

    m = re.search(r"from\s+([a-z][a-z ]*?)\s+to\s+([a-z][a-z ]*?)(?=\s*(?:this|next|on|for|in|,|\.|$|\d|with|under|budget|tomorrow|today))", lowered)
    if not m:
        m = re.search(r"\b([a-z]+)\s+to\s+([a-z]+)\b", lowered)
    if m and m.group(1) not in {"want", "going", "go", "trip", "travel", "planning", "plan"}:
        result["origin"] = m.group(1).strip().title()
        result["destination"] = m.group(2).strip().title()

    m = re.search(_NUM + r"\s*nights?", lowered)
    if m:
        result["nights"] = to_int(m.group(1))
    else:
        m = re.search(_NUM + r"\s*days?", lowered)
        if m and (to_int(m.group(1)) or 0) >= 2:
            result["nights"] = to_int(m.group(1)) - 1  # "3 days" = 2 nights

    m = re.search(
        r"(today|tonight|tomorrow|day after tomorrow|this (?:mon|tues|wednes|thurs|fri|satur|sun)day|"
        r"next (?:mon|tues|wednes|thurs|fri|satur|sun)day|this weekend|next weekend|next week|next month|"
        r"\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*|"
        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?|"
        r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|in (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)",
        lowered,
    )
    if m:
        result["date"] = m.group(1)
    return result


def parse_payments(text: str) -> dict:
    """Extract {"members": [...], "payments": {name: amount}} from free text."""
    payments: dict[str, int] = {}
    for m in re.finditer(
        r"([A-Z][a-zA-Z]+)\s+(?:has\s+|have\s+)?(?:paid|spent|put in|covered|gave)\s*(?:₹|rs\.?|inr)?\s*(\d[\d,]*k?)",
        text,
    ):
        amount = to_int(m.group(2))
        if amount is not None:
            payments[m.group(1)] = payments.get(m.group(1), 0) + amount
    for m in re.finditer(r"([A-Z][a-zA-Z]+)\s+(?:paid|spent)\s+(?:nothing|zero|0)\b", text):
        payments.setdefault(m.group(1), 0)

    members: list[str] = []
    stop = {
        "Plan", "Group", "Members", "We", "Us", "And", "Paid", "The", "I", "Approved", "Ok", "Okay",
        "Yes", "No", "Also", "Add", "Others", "Other", "Everyone", "Rest", "Nobody", "None", "That", "Thats",
    }
    first_clause = re.split(r"[.;\n]", text)[0]
    if "," in first_clause or " and " in first_clause or re.match(r"^\s*(?:also|add)\b", first_clause, re.IGNORECASE):
        for token in re.findall(r"[A-Z][a-zA-Z]+", first_clause):
            if token not in stop and token not in members:
                members.append(token)
    for name in payments:
        if name not in members:
            members.append(name)
    return {"members": members, "payments": payments}


_EXCLUSION = re.compile(
    r"\b([A-Z][a-zA-Z]+)\s+(?:skipped|missed|didn'?t\s+(?:have|join|eat|take|come for|share)|did not\s+(?:have|join|eat|take|share)|"
    r"wasn'?t\s+(?:at|there for|part of|in)|was not\s+(?:at|part of|in)|isn'?t\s+(?:in|part of)|"
    r"(?:is|was)\s+not\s+(?:in|part of)|didn'?t\s+go\s+(?:for|on))\s+(?:the\s+)?([a-z]+(?:\s[a-z]+)?)",
)
_EXPENSE = re.compile(
    r"\b([A-Z][a-zA-Z]+)\s+(?:has\s+|have\s+)?(?:paid|spent|put in|covered|gave)\s*(?:₹|rs\.?|inr)?\s*(\d[\d,]*k?)"
    r"(?:\s+(?:for|on)\s+(?:the\s+)?([a-z]+(?:\s[a-z]+)?))?",
)
_STOP_LABEL = {"everyone", "all", "us", "the", "group", "it"}


def parse_expenses(text: str) -> dict:
    """{"members", "expenses": [{payer, amount, label, excluded, only}], "exclusions": [{name, label}]}."""
    expenses = []
    for m in _EXPENSE.finditer(text):
        amount = to_int(m.group(2))
        if amount is None:
            continue
        label = (m.group(3) or "").strip().lower()
        label = "" if label in _STOP_LABEL else label.split(" except")[0]
        expenses.append({"payer": m.group(1), "amount": amount, "label": label, "excluded": [], "only": []})
    exclusions = [{"name": m.group(1), "label": m.group(2).strip().lower()} for m in _EXCLUSION.finditer(text)]
    simple = parse_payments(text)
    members = list(simple["members"])
    for ex in exclusions:
        if ex["name"] not in members:
            members.append(ex["name"])
    return {"members": members, "expenses": expenses, "exclusions": exclusions}


_PLAN_PATTERNS = [
    re.compile(r"plan[_\s-]?id[\s:=\"']*([abc])\b", re.IGNORECASE),
    re.compile(r"\b(?:plan|option)\s*([abc])\b", re.IGNORECASE),
    re.compile(r"^\s*([abc])\s*[.!]?\s*$", re.IGNORECASE),
]
_YES = re.compile(r"^\s*(yes|yep|yeah|yup|correct|confirm(?:ed)?|ok|okay|sure|go ahead|settle( it| up)?|looks good|that'?s right|y)\b", re.IGNORECASE)
_NO = re.compile(r"^\s*(no|nope|nah|not quite|wrong|incorrect|n)\b", re.IGNORECASE)


def parse_card_selection(text: str) -> dict | None:
    """Card taps arrive as JSON (direct @mention) or as prose (via the ASI:One planner)."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                selection = {k: str(v) for k, v in data.items() if k in ("action", "plan_id", "index")}
                if selection:
                    if "plan_id" in selection:
                        selection["plan_id"] = selection["plan_id"].upper()
                    return selection
        except json.JSONDecodeError:
            pass
    if re.search(r"new[_\s-]?trip|start over|reset", stripped, re.IGNORECASE):
        return {"action": "new_trip"}
    if re.search(r"confirm[_\s-]?settle", stripped, re.IGNORECASE):
        return {"action": "confirm_settle"}
    m = re.search(r"mark[_\s-]?paid.*?index[\s:=\"']*(\d+)|index[\s:=\"']*(\d+).*?mark[_\s-]?paid", stripped, re.IGNORECASE)
    if m:
        return {"action": "mark_paid", "index": m.group(1) or m.group(2)}
    for pattern in _PLAN_PATTERNS:
        m = pattern.search(stripped)
        if m:
            return {"action": "choose_plan", "plan_id": m.group(1).upper()}
    return None


def is_yes(text: str) -> bool:
    return bool(_YES.search(text or ""))


def is_no(text: str) -> bool:
    return bool(_NO.search(text or ""))


def merge_trip(base: dict, update: dict | None) -> dict:
    """Keep known values, fill missing ones from `update`."""
    merged = dict(base)
    for key, value in (update or {}).items():
        if value in (None, "", [], "null"):
            continue
        if key in ("people", "budget_amount", "nights"):
            value = value if isinstance(value, int) else to_int(str(value))
            if not value or value <= 0:
                continue
        if key == "budget_basis" and value not in ("per_person", "total"):
            continue
        merged[key] = value
    return merged


def budget_per_person(trip: dict) -> int | None:
    amount, basis, people = trip.get("budget_amount"), trip.get("budget_basis"), trip.get("people")
    if not amount or not basis:
        return None
    if basis == "per_person":
        return int(amount)
    if basis == "total" and people:
        return int(amount) // int(people)
    return None


def missing_questions(trip: dict) -> list[tuple[str, str]]:
    """What we still need to ask, in a natural order: (field, question)."""
    q: list[tuple[str, str]] = []
    if not trip.get("destination"):
        q.append(("destination", "Where do you want to go?"))
    if not trip.get("origin"):
        q.append(("origin", "Which city are you starting from?"))
    if not trip.get("people"):
        n = trip.get("people_hint")
        if n:
            q.append(("people", f"Is that {n} people in total, or {n} friends plus you ({n + 1})?"))
        else:
            q.append(("people", "How many people are going (including you)?"))
    if not trip.get("date"):
        q.append(("date", "When are you travelling?"))
    if not trip.get("nights"):
        q.append(("nights", "How many nights is the trip?"))
    if not trip.get("budget_amount"):
        q.append(("budget_amount", "What's your budget, and is it per person or for the whole group?"))
    elif not trip.get("budget_basis"):
        amount = trip["budget_amount"]
        q.append(("budget_basis", f"Is ₹{amount:,} per person or for the whole group?"))
    return q


def answer_for(field: str, text: str, hint: int | None = None) -> dict:
    """Read a short reply to exactly one question we asked. Returns {} if unclear."""
    stripped = text.strip().rstrip(".!")
    if field == "people" and hint:
        if re.search(r"plus (?:me|you)|including me|with me|\+\s*1|and me|me too|plus one", stripped, re.IGNORECASE):
            return {"people": hint + 1}
        if re.search(r"\btotal\b|in all|altogether|just|only|including", stripped, re.IGNORECASE) and not re.search(r"\d", stripped):
            return {"people": hint}
    if field in ("people", "nights"):
        m = re.search(_NUM, stripped.lower())
        value = to_int(m.group(1)) if m else None
        return {field: value} if value else {}
    if field == "budget_amount":
        m = re.search(_NUM, stripped.lower())
        value = to_int(m.group(1)) if m else None
        out = {"budget_amount": value} if value else {}
        basis = budget_basis(stripped)
        if basis:
            out["budget_basis"] = basis
        return out
    if field == "budget_basis":
        basis = budget_basis(stripped) or (
            "per_person" if re.search(r"\bper\b|person|head|individual", stripped, re.IGNORECASE)
            else "total" if re.search(r"group|whole|all|together", stripped, re.IGNORECASE) else None
        )
        return {"budget_basis": basis} if basis else {}
    if field in ("origin", "destination"):
        cleaned = re.sub(r"^(?:from|to|going to|i'?m in|we'?re in|starting from)\s+", "", stripped, flags=re.IGNORECASE)
        return {field: cleaned.title()} if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,40}", cleaned) else {}
    if field == "date":
        return {"date": stripped} if stripped else {}
    return {}
