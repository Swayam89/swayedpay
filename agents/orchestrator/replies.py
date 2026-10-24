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
    """Indian digit grouping: ₹1,12,840."""
    n = int(round(amount))
    sign, digits = ("-" if n < 0 else ""), str(abs(n))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    return f"{sign}₹{digits}"


def hours(h: float | None) -> str:
    if not h:
        return ""
    return "under 1h" if h < 1 else f"~{round(h)}h"


def transport_label(p: dict) -> str:
    t = hours(p.get("travel_hours"))
    return f"{p['transport']} ({t} each way)" if t else p["transport"]


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
    "Tell me about the trip: where from and to, how many people, when, how many nights, "
    "and your budget (per person or for the group). For example:\n"
    "*5 of us, Delhi to Jaipur this Saturday for 1 night, ₹4,000 each.*\n\n"
    "If anything is missing, I'll ask rather than guess."
)


def known_summary(trip: dict) -> str:
    parts = []
    if trip.get("origin") or trip.get("destination"):
        parts.append(f"{trip.get('origin') or '?'} → {trip.get('destination') or '?'}")
    if trip.get("people"):
        parts.append(f"{trip['people']} people")
    if trip.get("date"):
        parts.append(str(trip["date"]))
    if trip.get("nights"):
        parts.append(f"{trip['nights']} night{'s' if trip['nights'] != 1 else ''}")
    if trip.get("budget_amount"):
        basis = {"per_person": " per person", "total": " for the group"}.get(trip.get("budget_basis"), "")
        parts.append(f"{rupees(trip['budget_amount'])}{basis}")
    return " · ".join(parts)


def ask_questions(trip: dict, questions: list[tuple[str, str]], problem: str = "", hint: str = "") -> str:
    lines = []
    if problem:
        lines += [problem, ""]
    summary = known_summary(trip)
    if summary:
        lines += [f"So far: {summary}", ""]
    if len(questions) == 1:
        lines.append(f"One more thing: {questions[0][1]}")
    else:
        lines.append("Before I plan anything, a few questions:")
        lines += [f"{i}. {q}" for i, (_, q) in enumerate(questions, start=1)]
    if hint and any(f == "nights" for f, _ in questions):
        lines += ["", f"_{hint}_"]
    return "\n".join(lines)


def ask_missing_names(members: list[str], people: int) -> str:
    missing = people - len(members)
    have = ", ".join(members) if members else "none yet"
    return (
        f"You said {people} people are going, and I have {len(members)} name{'s' if len(members) != 1 else ''} "
        f"({have}). What {'is the name' if missing == 1 else 'are the names'} of the other {missing}?\n\n"
        "If the group is actually smaller, say *that's everyone*."
    )


def _who_shares(e: dict) -> str:
    if e.get("everyone"):
        return "shared by everyone"
    sharers = e.get("sharers") or []
    return f"shared by {', '.join(sharers)}"


def confirm_settlement(members: list[str], expenses: list[dict], people: int, preview: dict) -> tuple[str, dict[str, Any]]:
    total = preview["total"]
    lines = ["**Before I settle, please check this is right:**", ""]
    for e in preview["expenses"]:
        what = f" for {e['label']}" if e["label"] else ""
        lines.append(f"- {e['payer']} paid {rupees(e['amount'])}{what}, {_who_shares(e)}")
    non_payers = [n for n in preview["members"] if not preview["paid"].get(n)]
    if non_payers:
        lines.append(f"- {', '.join(non_payers)} paid nothing")
    lines.append("")
    if preview["equal"]:
        lines.append(f"Total {rupees(total)}, split **equally** between {len(preview['members'])} people ({rupees(preview['share'])} each).")
    else:
        lines.append(f"Total {rupees(total)}, **not** split equally. Each person's share:")
        lines += [f"- {n}: {rupees(preview['shares'][n])}" for n in preview["members"]]
    if people and len(preview["members"]) != people:
        lines.append(f"Note: you said {people} people earlier, but this list has {len(preview['members'])}.")
    lines += [
        "",
        "Reply **yes** to settle, or correct anything (e.g. *Dev paid 500*, *Kabir skipped dinner*, *remove Kabir*).",
    ]
    rows = [
        {"type": "text", "value": f"{n}: paid {rupees(preview['paid'].get(n, 0))} · share {rupees(preview['shares'][n])}", "style": "body"}
        for n in preview["members"]
    ]
    split = "split equally" if preview["equal"] else "uneven split"
    card = {
        "root": {
            "type": "section",
            "title": "Check before settling",
            "subtitle": f"{rupees(total)} total · {split}",
            "children": [
                {"type": "group", "direction": "column", "gap": 6, "children": rows},
                {"type": "divider"},
                {
                    "type": "button",
                    "label": "Yes, settle it",
                    "primary": True,
                    "action": {"selection": {"action": "confirm_settle"}},
                },
            ],
        }
    }
    return "\n".join(lines), card


def trip_summary(trip: dict) -> str:
    nights = trip.get("nights") or 1
    when = f", {str(trip['date']).title()}" if trip.get("date") else ""
    km = f" (~{trip['distance_km']:,} km)" if trip.get("distance_km") else ""
    return (
        f"{trip['origin']} → {trip['destination']}{km}{when} · {trip['people']} people · "
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
            f"**Plan {p['id']} · {p['name']}**: {transport_label(p)} + {p['stay']}, "
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
    ids = [f"**{p['id']}**" for p in plans]
    choices = ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " or " + ids[-1]
    lines += ["", f"Reply {choices}, or tap a plan on the card."]
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
                            {"type": "text", "value": f"{transport_label(p)} + {p['stay']}", "style": "body"},
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
        f"Plan {plan['id']} it is: {transport_label(plan)} + {plan['stay']}, "
        f"{rupees(plan['total'])} for the group.\n\n"
        f"Once you've spent money on the trip, tell me the names of all {people} people and who paid for what, for example:\n"
        "*Aman, Rahul, Dev, Isha, Kabir. Aman paid 9000 for the stay, Rahul paid 1500 for dinner. Kabir skipped dinner.*"
    )


def settlement_text(result: dict, plan: dict | None, note: str = "") -> str:
    if result.get("equal", True):
        head = (f"**Settled.** Total paid {rupees(result['total'])}, split {len(result['members'])} ways "
                f"({rupees(result['share'])} each).")
        lines = [head, ""]
    else:
        shares = ", ".join(f"{n} {rupees(result['shares'][n])}" for n in result["members"])
        lines = [f"**Settled.** Total paid {rupees(result['total'])}, split by who shared what: {shares}.", ""]
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
    lines += [
        "",
        "_No real money was moved through SwayedPay._ I'll keep track as people pay each other back: "
        "tell me *Dev paid Aman* or *Kabir paid Rahul 1000*, tap **Mark paid**, or ask *status*.",
    ]
    return "\n".join(lines)


def _left(t: dict) -> int:
    return int(t["amount"] - t.get("repaid", 0))


def tracker_text(result: dict) -> str:
    transfers = result["transfers"]
    if not transfers:
        return "Everyone is already square. Nothing to track."
    lines = ["**Payback tracker**", ""]
    for t in transfers:
        left = _left(t)
        if left <= 0:
            lines.append(f"- Paid: {t['from']} → {t['to']} {rupees(t['amount'])}")
        elif t.get("repaid"):
            lines.append(f"- Part paid: {t['from']} → {t['to']} {rupees(t['repaid'])} of {rupees(t['amount'])}, {rupees(left)} left")
        else:
            lines.append(f"- Pending: {t['from']} → {t['to']} {rupees(t['amount'])}")
    outstanding = sum(max(0, _left(t)) for t in transfers)
    lines.append("")
    lines.append("**Everyone is settled up.**" if outstanding == 0 else f"Still to be paid back: {rupees(outstanding)}.")
    return "\n".join(lines)


def tracker_card(result: dict) -> dict[str, Any]:
    items = []
    for i, t in enumerate(result["transfers"]):
        left = _left(t)
        status = "Paid" if left <= 0 else (f"{rupees(left)} left" if t.get("repaid") else "Pending")
        children: list[dict[str, Any]] = [{
            "type": "group", "direction": "column", "gap": 4, "children": [
                {"type": "text", "value": f"{t['from']} → {t['to']} · {rupees(t['amount'])}", "style": "body"},
                {"type": "badge", "label": status, "variant": "info"},
            ],
        }]
        if left > 0:
            children.append({
                "type": "button", "label": "Mark paid", "primary": False,
                "action": {"selection": {"action": "mark_paid", "index": str(i)}},
            })
        items.append({"children": children})
    outstanding = sum(max(0, _left(t)) for t in result["transfers"])
    body: list[dict[str, Any]] = [{"type": "list", "items": items}] if items else [
        {"type": "text", "value": "Everyone is already square.", "style": "body"}]
    return {
        "root": {
            "type": "section",
            "title": "Who pays whom",
            "subtitle": f"{rupees(result['total'])} total · {rupees(outstanding)} still to pay back",
            "children": body + [
                {"type": "divider"},
                {"type": "button", "label": "Plan another trip", "primary": False,
                 "action": {"selection": {"action": "new_trip"}}},
            ],
        }
    }
