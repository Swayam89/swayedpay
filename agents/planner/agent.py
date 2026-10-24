"""SwayedPay Planner agent: builds budget-checked trip plans for the orchestrator."""

import os

from uagents import Agent, Context

from agents.config import PLANNER_PORT, PLANNER_SEED
from agents.models import PlanRequest
from agents.planner.service import make_plan_response

planner = Agent(
    name="swayedpay-planner",
    seed=PLANNER_SEED,
    port=PLANNER_PORT,
    mailbox=True,
    publish_agent_details=True,
    readme_path=os.path.join(os.path.dirname(__file__), "README.md"),
)


@planner.on_event("startup")
async def startup(ctx: Context):
    ctx.logger.info(f"SwayedPay Planner running at {planner.address}")


@planner.on_message(PlanRequest)
async def handle_plan_request(ctx: Context, sender: str, req: PlanRequest):
    ctx.logger.info(f"Plan request: {req.origin} → {req.destination}, {req.people} people, ₹{req.budget_per_person} each")
    response = await make_plan_response(req)
    await ctx.send(sender, response)


if __name__ == "__main__":
    planner.run()
