"""SwayedPay Orchestrator: the agent users talk to in ASI:One.

Conversation per user (keyed by their ASI:One address):
  idle / need_info → (trip complete) → planning → choose_plan → need_payments → settling → done

The orchestrator uses ASI1 to understand free text, hands planning to the Planner
agent and splitting to the Settlement agent over agent messages, and replies to the
user over the Agent Chat Protocol. If a worker doesn't answer in time, it computes
the result itself with the same code and says so.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone

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
from agents.orchestrator import payments as pay
from agents.orchestrator import replies
from agents.parsing import merge_trip, missing_fields, parse_card_selection, parse_payments, parse_trip
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


def _new_session() -> dict:
    return {"stage": "idle", "trip": {}, "plans": [], "chosen": None, "pending": None}


def _session(user: str) -> dict:
    return SESSIONS.setdefault(user, _new_session())


async def _reply(ctx: Context, user: str, text: str, card: dict | None = None, end: bool = False) -> None:
    await ctx.send(user, replies.message(text, card=card, end_session=end))


# ---------- intake ----------

async def _understand_trip(text: str, known: dict) -> dict:
    """ASI1 first, rule-based parser for anything it misses."""
    prompt = text if not known else f"Known so far: {json.dumps(known)}. The user now says: {text}"
    llm = await asi1.extract_trip(prompt)
    trip = merge_trip(known, parse_trip(text))
    trip = merge_trip(trip, llm)
    # Short answers to a follow-up question ("Delhi", "5", "4000").
    stripped = text.strip().replace(",", "").replace("₹", "")
    if not llm and stripped.isdigit():
        value = int(stripped)
        if not trip.get("people") and value <= 50:
            trip["people"] = value
        elif not trip.get("budget_per_person"):
            trip["budget_per_person"] = value
    elif not llm and stripped.replace(" ", "").isalpha() and len(stripped.split()) <= 3:
        if not trip.get("origin"):
            trip["origin"] = stripped.title()
        elif not trip.get("destination"):
            trip["destination"] = stripped.title()
    return trip


async def _start_planning(ctx: Context, user: str, s: dict) -> None:
    trip = s["trip"]
    req = PlanRequest(
        user_address=user,
        origin=trip["origin"],
        destination=trip["destination"],
        people=int(trip["people"]),
        budget_per_person=int(trip["budget_per_person"]),
        nights=int(trip.get("nights") or 0),
        date=str(trip.get("date") or ""),
    )
    s["stage"] = "planning"
    s["pending"] = {"kind": "plan", "since": time.time(), "request": req.dict()}
    ctx.logger.info(f"Asking Planner for {user[:16]}…")
    await ctx.send(PLANNER_ADDRESS, req)


async def _start_settling(ctx: Context, user: str, s: dict, members: list[str], payments: dict) -> None:
    req = SettleRequest(user_address=user, members_json=json.dumps(members), payments_json=json.dumps(payments))
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
            await _reply(ctx, user, replies.ask_payments(plan, int(s["trip"]["people"])))
            return
        guess = parse_trip(text)
        if not (guess.get("destination") or guess.get("people")):
            ids = ", ".join(p["id"] for p in s["plans"])
            await _reply(ctx, user, f"Which plan would you like? Reply with {ids}, or say *new trip*.")
            return
        s.update(_new_session())  # looks like a fresh trip request

    if s["stage"] == "need_payments":
        llm = await asi1.extract_payments(text) or {}
        rule = parse_payments(text)
        payments = {}
        for source in (rule.get("payments") or {}, llm.get("payments") or {}):
            for name, amount in source.items():
                try:
                    payments[str(name).strip().title()] = int(float(str(amount).replace(",", "")))
                except ValueError:
                    continue
        members: list[str] = []
        for name in list(llm.get("members") or []) + list(rule.get("members") or []) + list(payments):
            name = str(name).strip().title()
            if name and name not in members:
                members.append(name)
        if not payments:
            await _reply(
                ctx, user,
                "I couldn't tell who paid what. Try: *Aman, Rahul, Dev, Isha, Kabir. Aman paid 9000, Rahul paid 4250.*",
            )
            return
        people = int(s["trip"].get("people") or len(members))
        i = 1
        while len(members) < people:
            filler = f"Friend {i}"
            if filler not in members:
                members.append(filler)
            i += 1
        if pay.fee_enabled():
            s["stage"] = "awaiting_payment"
            s["settle_args"] = {"members": members, "payments": payments}
            await _reply(
                ctx, user,
                f"Got it: {len(members)} people, {replies.rupees(sum(payments.values()))} paid in total. "
                f"Planning is free; settling costs a {pay.SETTLE_FEE_FET} testnet FET convenience fee. "
                "Approve the payment card and I'll split the bill.",
            )
            await _request_fee(ctx, user, s)
            return
        await _start_settling(ctx, user, s, members, payments)
        return

    # idle, need_info or done: treat as (part of) a trip request
    known = s["trip"] if s["stage"] == "need_info" else {}
    s["trip"] = await _understand_trip(text, known)
    missing = missing_fields(s["trip"])
    if missing:
        s["stage"] = "need_info"
        if not known and len(missing) >= 3:  # e.g. "hi": show what SwayedPay does
            await _reply(ctx, user, replies.GREETING)
        else:
            await _reply(ctx, user, replies.ask_missing(missing))
        return
    await _start_planning(ctx, user, s)


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
    await _start_settling(ctx, sender, s, args["members"], args["payments"])


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
    s["stage"] = "done"
    note = " ".join(n for n in (s.pop("payment_note", ""), note) if n)
    await _reply(
        ctx, user, replies.settlement_text(result, s.get("chosen"), note),
        card=replies.settlement_card(result), end=True,
    )


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
    ctx.logger.info(f"SwayedPay Orchestrator running at {orchestrator.address}")
    ctx.logger.info(f"Planner: {PLANNER_ADDRESS}")
    ctx.logger.info(f"Settlement: {SETTLEMENT_ADDRESS}")
    ctx.logger.info("ASI1: " + ("enabled" if asi1.enabled() else "DISABLED (no ASI_ONE_API_KEY, using rule-based parsing)"))
    ctx.logger.info(
        f"Payments: settle fee {pay.SETTLE_FEE_FET} testnet FET to {orchestrator.wallet.address()}"
        if pay.fee_enabled() else "Payments: off (PAYMENT_MODE=off)"
    )


if __name__ == "__main__":
    orchestrator.run()
