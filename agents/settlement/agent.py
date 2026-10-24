"""SwayedPay Settlement agent: splits a group's costs and returns who pays whom."""

import os

from uagents import Agent, Context

from agents.config import SETTLEMENT_PORT, SETTLEMENT_SEED
from agents.models import SettleRequest
from agents.settlement.service import make_settle_response

settlement = Agent(
    name="swayedpay-settlement",
    seed=SETTLEMENT_SEED,
    port=SETTLEMENT_PORT,
    mailbox=True,
    publish_agent_details=True,
    readme_path=os.path.join(os.path.dirname(__file__), "README.md"),
)


@settlement.on_event("startup")
async def startup(ctx: Context):
    ctx.logger.info(f"SwayedPay Settlement running at {settlement.address}")


@settlement.on_message(SettleRequest)
async def handle_settle_request(ctx: Context, sender: str, req: SettleRequest):
    ctx.logger.info("Settle request received")
    await ctx.send(sender, make_settle_response(req))


if __name__ == "__main__":
    settlement.run()
