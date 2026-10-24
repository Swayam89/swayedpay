"""Chat replies: plain text that always works, plus ASI:One Interactive Cards.

Cards use the custom element-tree format from Fetch.ai's news-card-agent example.
If ASI:One rejects a card, it falls back to showing the text, so every reply
stands on its own as text.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from uagents_core.contrib.protocols.chat import (
    AgentContent,
    ChatMessage,
    EndSessionContent,
    MetadataContent,
    TextContent,
)

CARD_PROTOCOL_VERSION = "1"


def rupees(amount: float) -> str:
    return f"₹{int(round(amount)):,}"


def message(text: str, card: dict[str, Any] | None = None, end_session: bool = False) -> ChatMessage:
    content: list[AgentContent] = [TextContent(type="text", text=text)]
    if card is not None:
        content.append(
            MetadataContent(
                type="metadata",
                metadata={
                    "card_protocol_version": CARD_PROTOCOL_VERSION,
                    "requires_card_interaction": "true",
                    "card_kind": "custom",
                    "card_payload": json.dumps(card),
                },
            )
        )
    if end_session:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


GREETING = (
    "Hi, I'm **SwayedPay**. I plan group trips that fit your budget and then settle who owes whom.\n\n"
    "Tell me the trip in one line, for example:\n"
    "*5 of us, Delhi to Jaipur this Saturday, ₹4,000 each max.*"
)


def ask_missing(missing: list[str]) -> str:
    if len(missing) == 1:
        need = missing[0]
    else:
        need = ", ".join(missing[:-1]) + " and " + missing[-1]
    return f"Happy to plan this. I still need {need}."


def trip_summary(trip: dict) -> str:
    nights = trip.get("nights") or 1
    when = f", {str(trip['date']).title()}" if trip.get("date") else ""
    return (
        f"{trip['origin']} → {trip['destination']}{when} · {trip['people']} people · "
        f"{rupees(trip['budget_per_person'])} each · {nights} night{'s' if nights != 1 else ''}"
    )


def plans_text(trip: dict, plans: list[dict], itinerary: list[str], data_label: str, note: str = "") -> str:
    lines = [f"**Your plans** ({trip_summary(trip)})", ""]
    if not any(p["within_budget"] for p in plans):
        cheapest = min(plans, key=lambda p: p["per_person"])
        lines.append(
            f"Nothing fits {rupees(trip['budget_per_person'])} per person. "
            f"The cheapest option is {rupees(cheapest['over_by'])} over. Here are your options:"
        )
        lines.append("")
    for p in plans:
        status = "fits your budget" if p["within_budget"] else f"{rupees(p['over_by'])} over budget"
        lines.append(
            f"**Plan {p['id']} · {p['name']}**: {p['transport']} + {p['stay']}, "
            f"{rupees(p['per_person'])} per person ({rupees(p['total'])} total), {status}."
        )
        b = p["breakdown"]
        lines.append(
            f"   Per person: travel {rupees(b['transport'])}, stay {rupees(b['stay'])}, "
            f"food {rupees(b['food'])}, local {rupees(b['local'])}."
        )
    swaps = plans[0].get("swaps") or []
    if swaps:
        lines += ["", "**How I fitted the budget for Plan A:**"] + [f"- {s}" for s in swaps]
    if itinerary:
        lines += ["", "**Suggested itinerary (ideas, not bookings):**"]
        lines += [f"- Day {i}: {d}" for i, d in enumerate(itinerary, start=1)]
    lines += ["", f"_{data_label}._"]
    if note:
        lines += ["", f"_{note}_"]
    lines += ["", "Reply **A**, **B** or **C**, or tap a plan on the card."]
    return "\n".join(lines)


def plans_card(trip: dict, plans: list[dict]) -> dict[str, Any]:
    items = []
    for p in plans:
        status = "Fits budget" if p["within_budget"] else f"{rupees(p['over_by'])} over budget"
        items.append(
            {
                "children": [
                    {
                        "type": "group",
                        "direction": "column",
                        "gap": 8,
                        "children": [
                            {"type": "heading", "value": f"Plan {p['id']} · {p['name']}", "level": 3},
                            {"type": "text", "value": f"{p['transport']} + {p['stay']}", "style": "body"},
                            {
                                "type": "text",
                                "value": f"{rupees(p['per_person'])} per person · {rupees(p['total'])} total",
                                "style": "body",
                            },
                            {"type": "badge", "label": status, "variant": "info"},
                        ],
                    },
                    {
                        "type": "button",
                        "label": f"Choose Plan {p['id']}",
                        "primary": p["id"] == "A",
                        "action": {"selection": {"action": "choose_plan", "plan_id": p["id"]}},
                    },
                ]
            }
        )
    return {
        "root": {
            "type": "section",
            "title": "SwayedPay plans",
            "subtitle": trip_summary(trip),
            "children": [{"type": "list", "items": items}],
        }
    }


def ask_payments(plan: dict, people: int) -> str:
    return (
        f"Plan {plan['id']} it is: {plan['transport']} + {plan['stay']}, "
        f"{rupees(plan['total'])} for the group.\n\n"
        f"Now tell me who's in the group of {people} and who paid what, for example:\n"
        "*Aman, Rahul, Dev, Isha, Kabir. Aman paid 9000, Rahul paid 4250.*"
    )


def settlement_text(result: dict, plan: dict | None, note: str = "") -> str:
    lines = [
        f"**Settled.** Total paid {rupees(result['total'])}, split {len(result['members'])} ways "
        f"({rupees(result['share'])} each).",
        "",
    ]
    if result["transfers"]:
        lines.append("**Who pays whom:**")
        lines += [f"- {t['from']} pays {t['to']} {rupees(t['amount'])}" for t in result["transfers"]]
    else:
        lines.append("Everyone has already paid their share. Nothing to settle.")
    if plan and result["total"] != plan["total"]:
        diff = result["total"] - plan["total"]
        word = "more" if diff > 0 else "less"
        lines += ["", f"_Note: the group paid {rupees(abs(diff))} {word} than the plan estimate of {rupees(plan['total'])}._"]
    if note:
        lines += ["", f"_{note}_"]
    lines += ["", "_No real money was moved. Share this list with your group to settle up._"]
    return "\n".join(lines)


def settlement_card(result: dict) -> dict[str, Any]:
    rows: list[dict[str, Any]] = [
        {"type": "text", "value": f"{t['from']} → {t['to']} · {rupees(t['amount'])}", "style": "body"}
        for t in result["transfers"]
    ] or [{"type": "text", "value": "Everyone is already square.", "style": "body"}]
    return {
        "root": {
            "type": "section",
            "title": "Who pays whom",
            "subtitle": f"{rupees(result['total'])} total · {rupees(result['share'])} each",
            "children": [
                {"type": "group", "direction": "column", "gap": 8, "children": rows},
                {"type": "divider"},
                {
                    "type": "button",
                    "label": "Plan another trip",
                    "primary": False,
                    "action": {"selection": {"action": "new_trip"}},
                },
            ],
        }
    }
