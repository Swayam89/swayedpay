"""Print each SwayedPay agent's address (derived from the seeds in .env) for the README."""

from uagents_core.identity import Identity

from agents.config import ORCHESTRATOR_SEED, PLANNER_SEED, SETTLEMENT_SEED

for name, seed in (
    ("SwayedPay (orchestrator)", ORCHESTRATOR_SEED),
    ("SwayedPay Planner", PLANNER_SEED),
    ("SwayedPay Settlement", SETTLEMENT_SEED),
):
    print(f"{name}: {Identity.from_seed(seed=seed, index=0).address}")
