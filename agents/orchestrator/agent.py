"""SwayedPay Orchestrator: the agent users talk to in ASI:One.

Conversation per user (keyed by their ASI:One address):
  idle / need_info → (trip complete) → planning → choose_plan → need_payments → settling → done

The orchestrator uses ASI1 to understand free text, hands planning to the Planner
agent and splitting to the Settlement agent over agent messages, and replies to the
user over the Agent Chat Protocol. If a worker doesn't answer in time, it computes
the result itself with the same code and says so.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from agents import asi1
from agents.config import (
    ORCHESTRATOR_PORT,
    ORCHESTRATOR_SEED,
    PLANNER_ADDRESS,
    SETTLEMENT_ADDRESS,
    WORKER_TIMEOUT_SECONDS,
)
from uagents_core.contrib.protocols.payment import CancelPayment, CommitPayment, CompletePayment, RejectPayment

from agents.models import PlanRequest, PlanResponse, SettleRequest, SettleResponse
from agents.orchestrator import booking
from agents.orchestrator import payments as pay
from agents.orchestrator import replies
from agents.settlement.logic import settle_expenses
from agents.data import geo
from agents.data.sample_prices import RouteError, build_route, suggested_nights
from agents.parsing import (
    answer_for,
    budget_per_person,
    is_no,
    is_yes,
    merge_trip,
    missing_questions,
    parse_card_selection,
    parse_expenses,
    parse_trip,
    to_int,
)
from agents.planner.service import make_plan_response
from agents.settlement.service import make_settle_response

orchestrator = Agent(
    name="swayedpay",
    seed=ORCHESTRATOR_SEED,
    port=ORCHESTRATOR_PORT,
    mailbox=True,
    publish_agent_details=True,
    readme_path=os.path.join(os.path.dirname(__file__), "README.md"),
)

chat_proto = Protocol(spec=chat_protocol_spec)

SESSIONS: dict[str, dict] = {}

# Conversations are saved to disk so a restart doesn't lose plans or the payback tracker.
STATE_FILE = Path(__file__).resolve().parents[2] / "sessions.json"
PERSIST = True


def _save() -> None:
    if not PERSIST:
        return
    try:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(SESSIONS))
        tmp.replace(STATE_FILE)
    except (OSError, TypeError, ValueError):
        pass


def _load() -> int:
    if not PERSIST or not STATE_FILE.exists():
        return 0
    try:
        data = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return 0
    for user, s in data.items():
        if s.get("stage") in ("planning", "settling"):
            s["pending"] = s.get("pending")  # the timeout check finishes these
        SESSIONS[user] = {**_new_session(), **s}
    return len(data)


def _new_session() -> dict:
    return {
        "stage": "idle", "trip": {}, "asked": [], "plans": [], "chosen": None, "pending": None,
        "members": [], "expenses": [], "pending_exclusions": [], "awaiting_names": False,
        "settlement": None,
    }


def _session(user: str) -> dict:
    return SESSIONS.setdefault(user, _new_session())


async def _reply(ctx: Context, user: str, text: str, card: dict | None = None, end: bool = False) -> None:
    await ctx.send(user, replies.message(text, card=card, end_session=end))


# ---------- intake: never guess, always ask ----------

async def _understand_trip(text: str, known: dict, asked: list) -> dict:
    """ASI1 first (with what we know and what we asked), rule-based parser as backup."""
    if known or asked:
        question = " ".join(q for _, q in asked)
        prompt = f"Known so far: {json.dumps(known)}. The agent just asked: {question} The user now says: {text}"
    else:
        prompt = text
    llm = await asi1.extract_trip(prompt)
    rule = parse_trip(text)
    trip = merge_trip(known, rule)
    trip = merge_trip(trip, llm)
    if rule.get("people_hint") and not known.get("people"):
        # "with 4 friends" is 4 or 5: never let a guess through, ask instead.
        trip["people"] = None
        trip["people_hint"] = rule["people_hint"]
    # A short reply to exactly one question is read as the answer to that question only.
    if len(asked) == 1 and not trip.get(asked[0][0]):
        trip = merge_trip(trip, answer_for(asked[0][0], text, trip.get("people_hint")))
    elif any(f == "people" for f, _ in asked) and trip.get("people_hint") and not trip.get("people"):
        trip = merge_trip(trip, answer_for("people", text, trip["people_hint"]))
    return trip


async def _check_places(trip: dict) -> str:
    """Validate the route as soon as both ends are known. Returns a problem to tell the user, or ''."""
    if not (trip.get("origin") and trip.get("destination")):
        return ""
    try:
        await asyncio.to_thread(build_route, trip["origin"], trip["destination"])
        return ""
    except RouteError as exc:
        for field in ("origin", "destination"):
            if not await asyncio.to_thread(geo.coords, trip[field]):
                trip[field] = None
                return str(exc)
        trip["destination"] = None
        return str(exc)


async def _nights_hint(trip: dict) -> str:
    if trip.get("nights") or not (trip.get("origin") and trip.get("destination")):
        return ""
    try:
        route = await asyncio.to_thread(build_route, trip["origin"], trip["destination"])
    except Exception:
        return ""
    n = suggested_nights(route)
    return f"For a ~{route['distance_km']:,} km trip, about {n} night{'s' if n != 1 else ''} usually works well, but it's your call."


async def _intake(ctx: Context, user: str, s: dict, text: str) -> None:
    known = s["trip"] if s["stage"] == "need_info" else {}
    asked = s["asked"] if s["stage"] == "need_info" else []
    trip = await _understand_trip(text, known, asked)
    s["trip"] = trip
    problem = await _check_places(trip)
    questions = missing_questions(trip)
    if questions:
        s["stage"] = "need_info"
        s["asked"] = questions
        if not known and not any(trip.get(k) for k in ("origin", "destination", "people", "budget_amount")):
            await _reply(ctx, user, replies.GREETING)  # e.g. "hi"
            return
        await _reply(ctx, user, replies.ask_questions(trip, questions, problem, await _nights_hint(trip)))
        return
    s["asked"] = []
    trip["budget_per_person"] = budget_per_person(trip)
    await _start_planning(ctx, user, s)


async def _start_planning(ctx: Context, user: str, s: dict) -> None:
    trip = s["trip"]
    req = PlanRequest(
        user_address=user,
        origin=trip["origin"],
        destination=trip["destination"],
        people=int(trip["people"]),
        budget_per_person=int(trip["budget_per_person"]),
        nights=int(trip["nights"]),
        date=str(trip.get("date") or ""),
    )
    s["stage"] = "planning"
    s["pending"] = {"kind": "plan", "since": time.time(), "request": req.dict()}
    ctx.logger.info(f"Asking Planner for {user[:16]}…")
    await ctx.send(PLANNER_ADDRESS, req)


async def _start_settling(ctx: Context, user: str, s: dict, members: list[str], expenses: list[dict]) -> None:
    req = SettleRequest(user_address=user, members_json=json.dumps(members), expenses_json=json.dumps(expenses))
    s["stage"] = "settling"
    s["pending"] = {"kind": "settle", "since": time.time(), "request": req.dict()}
    ctx.logger.info(f"Asking Settlement for {user[:16]}…")
    await ctx.send(SETTLEMENT_ADDRESS, req)


async def _request_fee(ctx: Context, user: str, s: dict) -> None:
    ctx.logger.info(f"Requesting {pay.SETTLE_FEE_FET} testnet FET from {user[:16]}…")
    await ctx.send(user, pay.build_request(str(orchestrator.wallet.address()), reference=user))


async def _handle_text(ctx: Context, user: str, text: str) -> None:
    s = _session(user)
    selection = parse_card_selection(text)

    if selection and selection.get("action") == "new_trip":
        SESSIONS[user] = _new_session()
        await _reply(ctx, user, replies.GREETING)
        return

    if s["stage"] in ("planning", "settling"):
        await _reply(ctx, user, "Still working on your last request. Give me a few seconds.")
        return

    if s["stage"] == "awaiting_payment":
        if "pay" in text.lower():
            await _request_fee(ctx, user, s)
        else:
            await _reply(
                ctx, user,
                f"To settle, approve the {pay.SETTLE_FEE_FET} testnet FET fee on the payment card. "
                "Reply *pay* to get the card again, or *new trip* to start over.",
            )
        return

    if s["stage"] == "choose_plan":
        plan_id = (selection or {}).get("plan_id")
        plan = next((p for p in s["plans"] if p["id"] == plan_id), None)
        if plan:
            s["chosen"] = plan
            s["stage"] = "need_payments"
            s["members"] = [m.title() for m in (s["trip"].get("members") or [])]
            s["expenses"], s["pending_exclusions"] = [], []
            text_out = replies.ask_payments(plan, int(s["trip"]["people"])) + "\n\n" + booking.links_markdown(plan, s["trip"])
            await _reply(ctx, user, text_out)
            return
        guess = parse_trip(text)
        if not (guess.get("destination") or guess.get("people")):
            ids = ", ".join(p["id"] for p in s["plans"])
            await _reply(ctx, user, f"Which plan would you like? Reply with {ids}, or say *new trip*.")
            return
        s.update(_new_session())  # looks like a fresh trip request

    if s["stage"] == "confirm_settle":
        if (selection or {}).get("action") == "confirm_settle" or is_yes(text):
            await _proceed_to_settle(ctx, user, s)
            return
        corrections = parse_expenses(text)
        if is_no(text) and not (corrections["expenses"] or corrections["members"] or corrections["exclusions"]):
            await _reply(
                ctx, user,
                "What should I change? For example: *Dev paid 500*, *Kabir skipped dinner*, *also add Priya*, or *remove Kabir*.",
            )
            return
        s["stage"] = "need_payments"  # treat the reply as corrections

    if s["stage"] == "need_payments":
        await _collect_payments(ctx, user, s, text)
        return

    if s["stage"] == "settled":
        if await _track_payback(ctx, user, s, text, selection):
            return
        guess = parse_trip(text)
        if not (guess.get("destination") or guess.get("people")):
            await _reply(
                ctx, user,
                "I'm tracking paybacks for this trip. Tell me when someone pays, e.g. *Dev paid Aman* "
                "or *Kabir paid Rahul 1000*, ask *status*, or say *new trip*.",
            )
            return
        s.update(_new_session())  # a fresh trip request

    # idle, need_info or done: treat as (part of) a trip request
    await _intake(ctx, user, s, text)


def _names_from_reply(text: str) -> list[str]:
    """A reply that is just names: 'Dev, Isha and Kabir' or 'Kabir'."""
    parts = re.split(r",|\band\b|&|\n", text)
    names = []
    for part in parts:
        part = part.strip().strip(".")
        if re.fullmatch(r"[A-Za-z][A-Za-z'-]{0,19}", part) and part.lower() not in {"also", "add", "and", "the", "others"}:
            names.append(part.title())
    return names


def _title_list(names) -> list[str]:
    return [str(n).strip().title() for n in (names or []) if str(n).strip()]


def _merge_expense(s: dict, e: dict) -> None:
    """Same payer + same purpose replaces the amount (a correction); otherwise it's a new expense."""
    try:
        amount = int(float(str(e.get("amount", "")).replace(",", "")))
    except ValueError:
        return
    payer = str(e.get("payer", "")).strip().title()
    if not payer or amount < 0:
        return
    label = re.sub(r"^the\s+", "", str(e.get("label") or "").strip().lower())
    excluded, only = _title_list(e.get("excluded")), _title_list(e.get("only"))
    for existing in s["expenses"]:
        if existing["payer"] == payer and existing["label"] == label:
            existing["amount"] = amount
            existing["excluded"] = sorted(set(existing["excluded"]) | set(excluded))
            if only:
                existing["only"] = only
            return
    s["expenses"].append({"payer": payer, "amount": amount, "label": label, "excluded": excluded, "only": only})


def _label_matches(wanted: str, label: str) -> bool:
    norm = lambda w: w.lower().rstrip("s")  # noqa: E731  ("drinks" ~ "drink")
    wanted_words = {norm(w) for w in wanted.split() if w}
    return bool(label) and bool(wanted_words & {norm(w) for w in label.split()})


def _apply_exclusions(s: dict) -> list[dict]:
    """Apply 'Kabir skipped dinner' to the matching expense. Returns the ones we can't place."""
    unresolved = []
    for ex in s["pending_exclusions"]:
        name, label = ex["name"].title(), ex["label"]
        matches = [e for e in s["expenses"] if _label_matches(label, e["label"])]
        if not matches:
            unresolved.append(ex)
            continue
        for e in matches:
            if name not in e["excluded"]:
                e["excluded"].append(name)
            e["only"] = [n for n in e["only"] if n != name]
    s["pending_exclusions"] = unresolved
    return unresolved


async def _collect_payments(ctx: Context, user: str, s: dict, text: str) -> None:
    if s.get("awaiting_names") and s["members"] and re.search(
        r"that'?s (?:everyone|all|it)|that is (?:everyone|all)|no ?one else|nobody else|only (?:us|them|these)|just (?:us|them|these)",
        text, re.IGNORECASE,
    ):
        s["awaiting_names"] = False
        s["trip"]["people"] = len(s["members"])
        await _confirm_or_ask(ctx, user, s)
        return

    removed = [n.title() for n in re.findall(r"remove\s+([A-Za-z]+)", text, re.IGNORECASE)]
    for name in removed:
        s["members"] = [m for m in s["members"] if m != name]
        s["expenses"] = [e for e in s["expenses"] if e["payer"] != name]
        for e in s["expenses"]:
            e["excluded"] = [n for n in e["excluded"] if n != name]
            e["only"] = [n for n in e["only"] if n != name]

    llm = await asi1.extract_expenses(text, s["members"]) or {}
    rule = parse_expenses(text)
    # Use ASI1's reading when it found expenses, else the rule-based one (never both: no double counting).
    expenses = llm.get("expenses") if isinstance(llm.get("expenses"), list) and llm.get("expenses") else rule["expenses"]
    for e in expenses:
        if isinstance(e, dict):
            _merge_expense(s, e)
    exclusions = [x for x in (llm.get("exclusions") or []) if isinstance(x, dict) and x.get("name") and x.get("label")]
    for x in exclusions or rule["exclusions"]:
        s["pending_exclusions"].append({"name": str(x["name"]).title(), "label": str(x["label"]).lower()})

    new_names = list(llm.get("members") or []) + list(rule.get("members") or [])
    new_names += [e["payer"] for e in s["expenses"]] + [x["name"] for x in s["pending_exclusions"]]
    if s.get("awaiting_names") and not new_names:
        new_names = _names_from_reply(text)
    for name in new_names:
        name = str(name).strip().title()
        if name and name not in s["members"] and name not in removed:
            s["members"].append(name)
    s["awaiting_names"] = False
    await _confirm_or_ask(ctx, user, s)


async def _confirm_or_ask(ctx: Context, user: str, s: dict) -> None:
    """Ask for whatever is still missing; otherwise show the summary to confirm."""
    people = int(s["trip"].get("people") or 0)
    if not s["expenses"]:
        await _reply(
            ctx, user,
            "Who paid for what so far? For example: *Aman paid 9000 for the stay, Rahul paid 1500 for dinner.* "
            "If nobody has paid yet, I can't settle anything.",
        )
        return
    unresolved = _apply_exclusions(s)
    if unresolved:
        ex = unresolved[0]
        await _reply(
            ctx, user,
            f"You said {ex['name']} wasn't part of the {ex['label']}, but I don't know which payment was the "
            f"{ex['label']}. Who paid for it, and how much? For example: *Rahul paid 1500 for {ex['label']}*.",
        )
        return
    if people and len(s["members"]) < people:
        s["awaiting_names"] = True
        await _reply(ctx, user, replies.ask_missing_names(s["members"], people))
        return
    try:
        preview = settle_expenses(s["members"], s["expenses"])
    except ValueError as exc:
        await _reply(ctx, user, f"That doesn't add up yet: {exc} Could you correct it?")
        return
    s["stage"] = "confirm_settle"
    text_out, card = replies.confirm_settlement(s["members"], s["expenses"], people, preview)
    await _reply(ctx, user, text_out, card=card)


async def _proceed_to_settle(ctx: Context, user: str, s: dict) -> None:
    members, expenses = list(s["members"]), [dict(e) for e in s["expenses"]]
    if pay.fee_enabled():
        s["stage"] = "awaiting_payment"
        s["settle_args"] = {"members": members, "expenses": expenses}
        await _reply(
            ctx, user,
            f"Confirmed: {len(members)} people, {replies.rupees(sum(e['amount'] for e in expenses))} paid in total. "
            f"Planning is free; settling costs a {pay.SETTLE_FEE_FET} testnet FET convenience fee. "
            "Approve the payment card and I'll split the bill.",
        )
        await _request_fee(ctx, user, s)
        return
    await _start_settling(ctx, user, s, members, expenses)


# ---------- payback tracking (after settling) ----------

_PAID_WORDS = re.compile(r"\b(paid|pays|sent|transferred|returned|repaid|settled|cleared|gave|done)\b", re.IGNORECASE)


def _mentioned(text: str, names: list[str]) -> list[str]:
    hits = []
    for name in names:
        m = re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE)
        if m:
            hits.append((m.start(), name))
    return [n for _, n in sorted(hits)]


async def _track_payback(ctx: Context, user: str, s: dict, text: str, selection: dict | None) -> bool:
    """Handle 'Dev paid Aman', 'Kabir paid Rahul 1000', 'status' or a Mark-paid tap. Returns True if handled."""
    result = s["settlement"]
    transfers = result["transfers"]

    if (selection or {}).get("action") == "mark_paid":
        i = int(selection.get("index", -1))
        if 0 <= i < len(transfers):
            transfers[i]["repaid"] = transfers[i]["amount"]
        await _reply(ctx, user, replies.tracker_text(result), card=replies.tracker_card(result))
        return True

    if re.search(r"\b(status|who owes|who still owes|pending|tracker|left to pay|balance)\b", text, re.IGNORECASE):
        await _reply(ctx, user, replies.tracker_text(result), card=replies.tracker_card(result))
        return True

    if not _PAID_WORDS.search(text):
        return False
    names = _mentioned(text, result["members"])
    if not names:
        await _reply(ctx, user, "Who paid whom? For example: *Dev paid Aman* or *Kabir paid Rahul 1000*.")
        return True
    payer, to = names[0], (names[1] if len(names) > 1 else None)
    amounts = re.findall(r"(?:₹|rs\.?\s*)?(\d[\d,]*k?)\b", text, re.IGNORECASE)
    amount = to_int(amounts[-1]) if amounts else None
    open_ = [t for t in transfers if t["from"] == payer and t["repaid"] < t["amount"] and (to is None or t["to"] == to)]

    if not open_:
        owes = [t for t in transfers if t["from"] == payer and t["repaid"] < t["amount"]]
        if not owes:
            await _reply(ctx, user, f"{payer} doesn't owe anyone anything right now.")
        else:
            listing = ", ".join(f"{t['to']} {replies.rupees(t['amount'] - t['repaid'])}" for t in owes)
            await _reply(ctx, user, f"{payer} doesn't owe {to}. {payer} still owes: {listing}.")
        return True

    if len(open_) > 1:
        remaining = {id(t): t["amount"] - t["repaid"] for t in open_}
        everything = re.search(r"\b(both|all|everyone|everything|in full|fully)\b", text, re.IGNORECASE)
        exact = [t for t in open_ if amount is not None and remaining[id(t)] == amount]
        if everything or (amount is not None and amount == sum(remaining.values())):
            for t in open_:
                t["repaid"] = t["amount"]
        elif len(exact) == 1:
            exact[0]["repaid"] = exact[0]["amount"]
        else:
            listing = " and ".join(f"{t['to']} {replies.rupees(remaining[id(t)])}" for t in open_)
            await _reply(
                ctx, user,
                f"{payer} owes {listing}. Who did {payer} pay? Say *{payer} paid {open_[0]['to']}*, "
                f"or *{payer} paid both*.",
            )
            return True
    else:
        t = open_[0]
        left = t["amount"] - t["repaid"]
        if amount is not None and amount > left:
            await _reply(
                ctx, user,
                f"{payer} only owes {t['to']} {replies.rupees(left)}, but you said {replies.rupees(amount)}. "
                f"Did {payer} pay the full {replies.rupees(left)}? If so, say *{payer} paid {t['to']}*.",
            )
            return True
        t["repaid"] += amount if amount is not None else left

    await _reply(ctx, user, replies.tracker_text(result), card=replies.tracker_card(result))
    return True


@chat_proto.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
    text = " ".join(c.text for c in msg.content if isinstance(c, TextContent) and c.text).strip()
    # ASI:One prefixes direct messages with the agent mention ("@agent1q… A"); drop it.
    text = re.sub(r"@agent1[a-z0-9]+\s*", "", text).strip()
    if not text:
        if any(isinstance(c, StartSessionContent) for c in msg.content):
            await _reply(ctx, sender, replies.GREETING)
        return
    ctx.logger.info(f"User {sender[:16]}…: {text}")
    try:
        await _handle_text(ctx, sender, text)
    except Exception as exc:  # never leave the user hanging
        ctx.logger.exception("Error handling message")
        SESSIONS[sender] = _new_session()
        await _reply(ctx, sender, f"Sorry, something went wrong on my side ({type(exc).__name__}). Let's start again: tell me the trip in one line.")
    _save()


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


orchestrator.include(chat_proto, publish_manifest=True)


# ---------- payment protocol (seller) ----------

@pay.payment_proto.on_message(CommitPayment)
async def on_commit_payment(ctx: Context, sender: str, msg: CommitPayment):
    s = _session(sender)
    if s["stage"] != "awaiting_payment" or not s.get("settle_args"):
        await ctx.send(sender, CancelPayment(transaction_id=msg.transaction_id, reason="No settlement is waiting for payment."))
        return
    buyer = ""
    if isinstance(msg.metadata, dict):
        buyer = str(msg.metadata.get("buyer_fet_wallet") or msg.metadata.get("buyer_fet_address") or "")
    ok, reason = False, "unsupported payment method"
    if msg.funds.currency == "FET" and msg.funds.payment_method == "fet_direct":
        ok, reason = await pay.verify_payment(
            msg.transaction_id, pay.SETTLE_FEE_FET, buyer, str(orchestrator.wallet.address())
        )
    ctx.logger.info(f"Payment {msg.transaction_id}: {reason}")
    if not ok:
        await ctx.send(sender, CancelPayment(transaction_id=msg.transaction_id, reason=reason))
        await _reply(ctx, sender, f"I couldn't verify that payment: {reason}. Reply *pay* to try again.")
        return
    await ctx.send(sender, CompletePayment(transaction_id=msg.transaction_id))
    s["payment_note"] = f"Settlement fee of {pay.SETTLE_FEE_FET} testnet FET verified on the Dorado testnet (tx {msg.transaction_id[:12]}…)."
    args = s.pop("settle_args")
    await _start_settling(ctx, sender, s, args["members"], args["expenses"])


@pay.payment_proto.on_message(RejectPayment)
async def on_reject_payment(ctx: Context, sender: str, msg: RejectPayment):
    ctx.logger.info(f"Payment rejected by {sender[:16]}…: {msg.reason}")
    await _reply(
        ctx, sender,
        "No problem, the payment was declined, so I haven't settled the bill. Reply *pay* if you change your mind, or *new trip* to start over.",
    )


orchestrator.include(pay.payment_proto, publish_manifest=True)


# ---------- worker results ----------

async def _deliver_plans(ctx: Context, resp: PlanResponse, note: str = "") -> None:
    user = resp.user_address
    s = _session(user)
    if s["stage"] != "planning":
        return
    s["pending"] = None
    if resp.error:
        s["stage"] = "need_info"
        await _reply(ctx, user, f"I couldn't build plans: {resp.error}. Could you check the trip details?")
        return
    plans = json.loads(resp.plans_json)
    s["plans"] = plans
    s["stage"] = "choose_plan"
    s["trip"]["nights"] = resp.nights
    s["trip"]["distance_km"] = resp.distance_km
    extra = json.loads(resp.notes_json or "[]")
    if resp.nights_assumed:
        extra.insert(0, f"You didn't say how long, so I planned {resp.nights} night{'s' if resp.nights != 1 else ''} to suit the ~{resp.distance_km:,} km journey.")
    note = " ".join(extra + ([note] if note else []))
    text = replies.plans_text(s["trip"], plans, json.loads(resp.itinerary_json or "[]"), resp.data_label, note)
    await _reply(ctx, user, text, card=replies.plans_card(s["trip"], plans))
    _save()


async def _deliver_settlement(ctx: Context, resp: SettleResponse, note: str = "") -> None:
    user = resp.user_address
    s = _session(user)
    if s["stage"] != "settling":
        return
    s["pending"] = None
    if resp.error:
        s["stage"] = "need_payments"
        await _reply(ctx, user, f"I couldn't settle that: {resp.error} Please send who paid what again.")
        return
    result = json.loads(resp.result_json)
    for t in result["transfers"]:
        t.setdefault("repaid", 0)
    s["settlement"] = result
    s["stage"] = "settled"  # stays open as a payback tracker
    note = " ".join(n for n in (s.pop("payment_note", ""), note) if n)
    await _reply(
        ctx, user, replies.settlement_text(result, s.get("chosen"), note),
        card=replies.tracker_card(result),
    )
    _save()


@orchestrator.on_message(PlanResponse)
async def on_plan_response(ctx: Context, sender: str, resp: PlanResponse):
    ctx.logger.info("Plans received from Planner agent")
    await _deliver_plans(ctx, resp)


@orchestrator.on_message(SettleResponse)
async def on_settle_response(ctx: Context, sender: str, resp: SettleResponse):
    ctx.logger.info("Settlement received from Settlement agent")
    await _deliver_settlement(ctx, resp)


@orchestrator.on_interval(period=5.0)
async def check_timeouts(ctx: Context):
    """Recovery path: if a worker agent is down or slow, finish the job locally."""
    now = time.time()
    for user, s in list(SESSIONS.items()):
        pending = s.get("pending")
        if not pending or now - pending["since"] < WORKER_TIMEOUT_SECONDS:
            continue
        if pending["kind"] == "plan":
            ctx.logger.warning("Planner timed out; computing plans locally")
            resp = await make_plan_response(PlanRequest(**pending["request"]))
            await _deliver_plans(ctx, resp, note="The Planner agent didn't answer in time, so I built these plans myself.")
        else:
            ctx.logger.warning("Settlement timed out; settling locally")
            resp = make_settle_response(SettleRequest(**pending["request"]))
            await _deliver_settlement(ctx, resp, note="The Settlement agent didn't answer in time, so I settled this myself.")


@orchestrator.on_event("startup")
async def startup(ctx: Context):
    loaded = _load()
    ctx.logger.info(f"SwayedPay Orchestrator running at {orchestrator.address}")
    ctx.logger.info(f"Restored {loaded} saved conversation(s) from {STATE_FILE.name}")
    ctx.logger.info(f"Planner: {PLANNER_ADDRESS}")
    ctx.logger.info(f"Settlement: {SETTLEMENT_ADDRESS}")
    ctx.logger.info("ASI1: " + ("enabled" if asi1.enabled() else "DISABLED (no ASI_ONE_API_KEY, using rule-based parsing)"))
    ctx.logger.info(
        f"Payments: settle fee {pay.SETTLE_FEE_FET} testnet FET to {orchestrator.wallet.address()}"
        if pay.fee_enabled() else "Payments: off (PAYMENT_MODE=off)"
    )


if __name__ == "__main__":
    orchestrator.run()
