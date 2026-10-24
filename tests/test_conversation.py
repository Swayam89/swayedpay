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


class FakeCtx:
    def __init__(self, deliver_workers: bool = True):
        self.logger = logging.getLogger("test")
        self.to_user: list[ChatMessage] = []
        self.deliver_workers = deliver_workers

    async def send(self, address, msg):
        if address == USER:
            if isinstance(msg, ChatMessage):
                self.to_user.append(msg)
        elif address == PLANNER_ADDRESS and self.deliver_workers:
            await orch._deliver_plans(self, await make_plan_response(msg))
        elif address == SETTLEMENT_ADDRESS and self.deliver_workers:
            await orch._deliver_settlement(self, make_settle_response(msg))

    def last_text(self) -> str:
        return " ".join(c.text for c in self.to_user[-1].content if isinstance(c, TextContent))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(asi1, "ASI_ONE_API_KEY", "")
    orch.SESSIONS.clear()


def test_full_flow_with_card_selection():
    ctx = FakeCtx()

    async def run():
        await orch._handle_text(ctx, USER, "5 of us, Delhi to Jaipur this Saturday, ₹4,000 each max")
        assert "Plan A" in ctx.last_text()
        assert any(isinstance(c, MetadataContent) for c in ctx.to_user[-1].content)
        assert "Sample estimates" in ctx.last_text()

        await orch._handle_text(ctx, USER, '{"action": "choose_plan", "plan_id": "A"}')
        assert "who paid what" in ctx.last_text()

        await orch._handle_text(ctx, USER, "Aman, Rahul, Dev, Isha, Kabir. Aman paid 9000, Rahul paid 4250.")
        final = ctx.last_text()
        assert "Settled" in final and "pays Aman" in final
        assert any(isinstance(c, EndSessionContent) for c in ctx.to_user[-1].content)
        assert orch.SESSIONS[USER]["stage"] == "done"

    asyncio.run(run())


def test_asks_for_missing_details_then_plans():
    ctx = FakeCtx()

    async def run():
        await orch._handle_text(ctx, USER, "Delhi to Agra trip, 4 friends")
        assert "budget per person" in ctx.last_text()
        await orch._handle_text(ctx, USER, "3500")
        assert "Plan A" in ctx.last_text()

    asyncio.run(run())


def test_worker_timeout_falls_back_locally(monkeypatch):
    ctx = FakeCtx(deliver_workers=False)

    async def run():
        await orch._handle_text(ctx, USER, "5 of us, Delhi to Jaipur, ₹4,000 each")
        assert orch.SESSIONS[USER]["stage"] == "planning"
        orch.SESSIONS[USER]["pending"]["since"] -= 999
        await orch.check_timeouts(ctx)
        assert "built these plans myself" in ctx.last_text()
        assert orch.SESSIONS[USER]["stage"] == "choose_plan"

    asyncio.run(run())
