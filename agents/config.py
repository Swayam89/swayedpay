"""Shared configuration: seeds, addresses and ports for the three SwayedPay agents."""

import os

from dotenv import find_dotenv, load_dotenv
from uagents_core.identity import Identity

load_dotenv(find_dotenv())


def _seed(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill in a random seed phrase."
        )
    return value


ORCHESTRATOR_SEED = _seed("ORCHESTRATOR_SEED_PHRASE")
PLANNER_SEED = _seed("PLANNER_SEED_PHRASE")
SETTLEMENT_SEED = _seed("SETTLEMENT_SEED_PHRASE")

PLANNER_ADDRESS = Identity.from_seed(seed=PLANNER_SEED, index=0).address
SETTLEMENT_ADDRESS = Identity.from_seed(seed=SETTLEMENT_SEED, index=0).address

ORCHESTRATOR_PORT = int(os.getenv("ORCHESTRATOR_PORT", "8010"))
PLANNER_PORT = int(os.getenv("PLANNER_PORT", "8011"))
SETTLEMENT_PORT = int(os.getenv("SETTLEMENT_PORT", "8012"))

# Seconds the orchestrator waits for a worker agent before computing the answer itself.
WORKER_TIMEOUT_SECONDS = float(os.getenv("WORKER_TIMEOUT_SECONDS", "30"))
