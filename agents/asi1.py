"""ASI1 LLM client (OpenAI-style chat completions on https://api.asi1.ai/v1).

Every call degrades gracefully: if the key is missing or the request fails, callers
get None and fall back to the rule-based parsers in `agents.parsing`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

import requests
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

ASI_ONE_API_KEY = (os.getenv("ASI_ONE_API_KEY") or "").strip()
ASI_ONE_MODEL = os.getenv("ASI_ONE_MODEL", "asi1")
ASI_ONE_CHAT_URL = "https://api.asi1.ai/v1/chat/completions"


def enabled() -> bool:
    return bool(ASI_ONE_API_KEY)


def _chat_completion(messages: list[dict[str, str]], max_tokens: int, temperature: float) -> str | None:
    if not ASI_ONE_API_KEY:
        return None
    payload: dict[str, Any] = {
        "model": ASI_ONE_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {ASI_ONE_API_KEY}", "Content-Type": "application/json"}
    try:
        resp = requests.post(ASI_ONE_CHAT_URL, json=payload, headers=headers, timeout=45)
        if not resp.ok:
            return None
        choices = resp.json().get("choices") or []
        if not choices:
            return None
        return (choices[0].get("message") or {}).get("content")
    except Exception:
        return None


async def chat(messages: list[dict[str, str]], max_tokens: int = 400, temperature: float = 0.2) -> str | None:
    return await asyncio.to_thread(_chat_completion, messages, max_tokens, temperature)


def extract_json(text: str | None) -> dict | None:
    """Pull the first JSON object out of an LLM reply (tolerates ```json fences)."""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


TRIP_SYSTEM_PROMPT = """You extract group-trip requests into JSON for a trip-planning agent in India.
Reply with ONLY a JSON object with these keys:
- "origin": departure city or null
- "destination": destination city or null
- "people": number of travellers as an integer, or null. "with 4 friends" is ambiguous (4 or 5 including the user): use null unless they said the total (e.g. "5 of us", "5 people in total")
- "budget_amount": the budget in rupees exactly as stated, as an integer (10k = 10000), or null
- "budget_basis": "per_person" if they said each / per person / per head, "total" if they said total / for the group / for all of us, otherwise null
- "nights": number of nights as an integer, or null. "3 days" means 2 nights. A bare "weekend" or "trip" is NOT a number of nights: use null.
- "date": when they travel, as the user wrote it, or null
- "members": list of names of people in the group if given, else []
Never guess. If something is not clearly stated, use null so the agent can ask.
You may be told what is known so far and what the agent just asked; use that to interpret short answers like "5" or "per person"."""


async def extract_trip(text: str) -> dict | None:
    reply = await chat(
        [{"role": "system", "content": TRIP_SYSTEM_PROMPT}, {"role": "user", "content": text}],
        max_tokens=300,
        temperature=0.0,
    )
    return extract_json(reply)


EXPENSES_SYSTEM_PROMPT = """You extract a travel group's shared expenses for a bill-splitting agent.
Reply with ONLY a JSON object:
- "members": every person's name mentioned as part of the group (include payers)
- "expenses": list of {"payer": name, "amount": integer rupees, "label": what it was for in 1-2 lowercase words or "",
   "excluded": names who did NOT share this expense, "only": names who were the ONLY ones sharing it (else [])}
- "exclusions": list of {"name": name, "label": 1-2 lowercase words} for statements like "Kabir skipped dinner"
   or "Isha didn't have drinks" that do not themselves state a payment
Rules: never invent names or amounts. If an expense doesn't say who shared it, leave "excluded" and "only" empty.
"Aman paid 9000" with no purpose has label "". Use the same label words the user used."""


async def extract_expenses(text: str, members: list[str] | None = None) -> dict | None:
    context = f"Group members so far: {', '.join(members)}. " if members else ""
    reply = await chat(
        [{"role": "system", "content": EXPENSES_SYSTEM_PROMPT}, {"role": "user", "content": context + text}],
        max_tokens=500,
        temperature=0.0,
    )
    return extract_json(reply)


async def write_itinerary(destination: str, nights: int) -> list[str] | None:
    """Short day-by-day suggestions. Ideas only: the agent never presents these as bookings."""
    days = nights + 1
    reply = await chat(
        [
            {
                "role": "system",
                "content": (
                    "You suggest short, practical group-trip itineraries in India. "
                    f"Reply with ONLY a JSON object {{\"days\": [..]}} holding exactly {days} strings, "
                    "one per day, each under 20 words. No prices."
                ),
            },
            {"role": "user", "content": f"A {days}-day trip to {destination} for a group of friends."},
        ],
        max_tokens=300,
        temperature=0.5,
    )
    data = extract_json(reply)
    if not data:
        return None
    days_list = data.get("days")
    if isinstance(days_list, list) and all(isinstance(d, str) for d in days_list) and days_list:
        return days_list[:days]
    return None
