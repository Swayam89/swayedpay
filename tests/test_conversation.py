"""End-to-end conversation test with an in-process fake transport (no network, no ASI1)."""

import asyncio
import logging

import pytest
from uagents_core.contrib.protocols.chat import ChatMessage, EndSessionContent, MetadataContent, TextContent

from agents import asi1
from agents.config import PLANNER_ADDRESS, SETTLEMENT_ADDRESS
from agents.orchestrator import agent as orch
from agents.planner.service import make_plan_response
from agents.settlement.service import make_settle_response

USER = "agent1quser"
FULL = "5 of us, Delhi to Jaipur this Saturday for 1 night, ₹4,000 each"


class FakeCtx:
    def __init__(self, deliver_workers: bool = True):
        self.logger = logging.getLogger("test")
        self.to_user: list[ChatMessage] = []
        self.other_to_user: list = []
        self.deliver_workers = deliver_workers

    async def send(self, address, msg):
        if address == USER:
            if isinstance(msg, ChatMessage):
                self.to_user.append(msg)
            else:
                self.other_to_user.append(msg)
        elif address == PLANNER_ADDRESS and self.deliver_workers:
            await orch._deliver_plans(self, await make_plan_response(msg))
        elif address == SETTLEMENT_ADDRESS and self.deliver_workers:
            await orch._deliver_settlement(self, make_settle_response(msg))

    def last_text(self) -> str:
        return " ".join(c.text for c in self.to_user[-1].content if isinstance(c, TextContent))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    from agents.orchestrator import payments

    monkeypatch.setattr(asi1, "ASI_ONE_API_KEY", "")
    monkeypatch.setattr(payments, "PAYMENT_MODE", "off")  # tests opt in explicitly
    orch.SESSIONS.clear()


def test_full_flow_with_card_selection():
    ctx = FakeCtx()

    async def run():
        await orch._handle_text(ctx, USER, FULL)
        assert "Plan A" in ctx.last_text()
        assert any(isinstance(c, MetadataContent) for c in ctx.to_user[-1].content)
        assert "not live fares" in ctx.last_text()

        await orch._handle_text(ctx, USER, '{"action": "choose_plan", "plan_id": "A"}')
        assert "who has paid what" in ctx.last_text()

        await orch._handle_text(ctx, USER, "Aman, Rahul, Dev, Isha, Kabir. Aman paid 9000, Rahul paid 4250.")
        check = ctx.last_text()
        assert "Before I settle" in check and "Dev, Isha, Kabir paid nothing" in check
        assert orch.SESSIONS[USER]["stage"] == "confirm_settle"

        await orch._handle_text(ctx, USER, '{"action": "confirm_settle"}')
        final = ctx.last_text()
        assert "Settled" in final and "pays Aman" in final
        assert any(isinstance(c, EndSessionContent) for c in ctx.to_user[-1].content)
        assert orch.SESSIONS[USER]["stage"] == "done"

    asyncio.run(run())


def test_asks_for_every_missing_detail_then_plans():
    ctx = FakeCtx()

    async def run():
        await orch._handle_text(ctx, USER, "Delhi to Agra trip, 4 friends")
        ask = ctx.last_text()
        assert "When are you travelling?" in ask and "How many nights" in ask and "budget" in ask
        assert orch.SESSIONS[USER]["stage"] == "need_info"
        await orch._handle_text(ctx, USER, "next saturday, 1 night, 3500 each")
        assert "Plan A" in ctx.last_text()

    asyncio.run(run())


def test_nights_are_never_assumed():
    ctx = FakeCtx()

    async def run():
        await orch._handle_text(ctx, USER, "5 of us, Surat to Delhi next Friday, ₹10,000 each")
        ask = ctx.last_text()
        assert "How many nights" in ask and "usually works well" in ask
        await orch._handle_text(ctx, USER, "3")
        assert "Plan A" in ctx.last_text() and "3 nights" in ctx.last_text()

    asyncio.run(run())


def test_budget_basis_is_asked_not_assumed():
    ctx = FakeCtx()

    async def run():
        await orch._handle_text(ctx, USER, "5 of us, Delhi to Jaipur this Saturday for 1 night, budget 20000")
        assert "per person or for the whole group" in ctx.last_text()
        await orch._handle_text(ctx, USER, "for the whole group")
        assert orch.SESSIONS[USER]["trip"]["budget_per_person"] == 4000
        assert "Plan A" in ctx.last_text()

    asyncio.run(run())


def test_weekend_is_not_read_as_a_number_of_nights():
    ctx = FakeCtx()

    async def run():
        await orch._handle_text(ctx, USER, "weekend trip, 4 of us, Mumbai to Lonavala this weekend, 3000 each")
        assert "How many nights" in ctx.last_text()

    asyncio.run(run())


def test_missing_names_are_asked_and_corrections_work():
    ctx = FakeCtx()

    async def run():
        await orch._handle_text(ctx, USER, FULL)
        await orch._handle_text(ctx, USER, "A")
        await orch._handle_text(ctx, USER, "Aman paid 9000, Rahul paid 4250")
        assert "other 3" in ctx.last_text()
        await orch._handle_text(ctx, USER, "Dev, Isha and Kabir")
        assert "Before I settle" in ctx.last_text()
        await orch._handle_text(ctx, USER, "Dev paid 500")
        assert "Dev paid ₹500" in ctx.last_text()
        await orch._handle_text(ctx, USER, "yes")
        assert "Settled" in ctx.last_text() and "₹13,750" in ctx.last_text()

    asyncio.run(run())


def test_worker_timeout_falls_back_locally(monkeypatch):
    ctx = FakeCtx(deliver_workers=False)

    async def run():
        await orch._handle_text(ctx, USER, FULL)
        assert orch.SESSIONS[USER]["stage"] == "planning"
        orch.SESSIONS[USER]["pending"]["since"] -= 999
        await orch.check_timeouts(ctx)
        assert "built these plans myself" in ctx.last_text()
        assert orch.SESSIONS[USER]["stage"] == "choose_plan"

    asyncio.run(run())


# ---------- payment protocol ----------

from uagents_core.contrib.protocols.payment import (  # noqa: E402
    CancelPayment,
    CommitPayment,
    CompletePayment,
    Funds,
    RejectPayment,
    RequestPayment,
)

from agents.orchestrator import payments as pay  # noqa: E402


async def _to_payment_step(ctx):
    await orch._handle_text(ctx, USER, FULL)
    await orch._handle_text(ctx, USER, "A")
    await orch._handle_text(ctx, USER, "Aman, Rahul, Dev, Isha, Kabir. Aman paid 9000, Rahul paid 4250.")
    await orch._handle_text(ctx, USER, "yes")


def _commit(tx="ABC123TX"):
    return CommitPayment(
        funds=Funds(amount="0.1", currency="FET", payment_method="fet_direct"),
        recipient="fetch1x",
        transaction_id=tx,
        metadata={"buyer_fet_wallet": "fetch1buyer"},
    )


def test_settle_fee_requests_payment_then_settles(monkeypatch):
    monkeypatch.setattr(pay, "PAYMENT_MODE", "settle_fee")

    async def ok(*args):
        return True, "verified"

    monkeypatch.setattr(pay, "verify_payment", ok)
    ctx = FakeCtx()

    async def run():
        await _to_payment_step(ctx)
        assert orch.SESSIONS[USER]["stage"] == "awaiting_payment"
        request = ctx.other_to_user[-1]
        assert isinstance(request, RequestPayment)
        assert request.accepted_funds[0].currency == "FET"
        assert request.metadata["fet_network"] == "stable-testnet"

        await orch.on_commit_payment(ctx, USER, _commit())
        assert any(isinstance(m, CompletePayment) for m in ctx.other_to_user)
        final = ctx.last_text()
        assert "Settled" in final and "verified on the Dorado testnet" in final

    asyncio.run(run())


def test_failed_verification_cancels_and_waits(monkeypatch):
    monkeypatch.setattr(pay, "PAYMENT_MODE", "settle_fee")

    async def bad(*args):
        return False, "no matching transfer to SwayedPay's wallet was found"

    monkeypatch.setattr(pay, "verify_payment", bad)
    ctx = FakeCtx()

    async def run():
        await _to_payment_step(ctx)
        await orch.on_commit_payment(ctx, USER, _commit())
        assert isinstance(ctx.other_to_user[-1], CancelPayment)
        assert "couldn't verify" in ctx.last_text()
        assert orch.SESSIONS[USER]["stage"] == "awaiting_payment"

    asyncio.run(run())


def test_rejected_payment_does_not_settle(monkeypatch):
    monkeypatch.setattr(pay, "PAYMENT_MODE", "settle_fee")
    ctx = FakeCtx()

    async def run():
        await _to_payment_step(ctx)
        await orch.on_reject_payment(ctx, USER, RejectPayment(reason="no"))
        assert "declined" in ctx.last_text()
        assert orch.SESSIONS[USER]["stage"] == "awaiting_payment"

    asyncio.run(run())


def test_asi_one_mention_prefix_is_stripped():
    """ASI:One sends '@agent1q… A'; the bare plan letter must still be understood."""
    from datetime import datetime, timezone
    from uuid import uuid4

    ctx = FakeCtx()
    mention = "@agent1q2s8r5839dwshsem7sttwpkxmy59xvde0hjpms75fnc49hdwlwm0vw43ann"

    def chat(text):
        return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=[TextContent(type="text", text=text)])

    async def run():
        await orch.handle_chat(ctx, USER, chat(f"{mention} {FULL}"))
        assert orch.SESSIONS[USER]["stage"] == "choose_plan"
        await orch.handle_chat(ctx, USER, chat(f"{mention} A"))
        assert orch.SESSIONS[USER]["stage"] == "need_payments"

    asyncio.run(run())


def test_with_n_friends_is_asked_not_guessed():
    ctx = FakeCtx()

    async def run():
        await orch._handle_text(ctx, USER, "Pune to Goa with 4 friends on 12 dec for 2 nights, 8000 each")
        assert "4 people in total, or 4 friends plus you (5)" in ctx.last_text()
        await orch._handle_text(ctx, USER, "plus me")
        assert orch.SESSIONS[USER]["trip"]["people"] == 5
        assert "Plan A" in ctx.last_text()

    asyncio.run(run())
