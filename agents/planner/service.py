"""Planner workflow, shared by the Planner agent and the orchestrator's fallback path."""

import asyncio
import json

from agents import asi1
from agents.models import PlanRequest, PlanResponse
from agents.planner.logic import build_plans


async def make_plan_response(req: PlanRequest) -> PlanResponse:
    try:
        # Runs in a thread: looking up an unfamiliar town may call OpenStreetMap.
        result = await asyncio.to_thread(
            build_plans, req.origin, req.destination, req.people, req.budget_per_person, req.nights
        )
    except ValueError as exc:
        return PlanResponse(user_address=req.user_address, error=str(exc))
    itinerary = await asi1.write_itinerary(req.destination, result["nights"]) or []
    return PlanResponse(
        user_address=req.user_address,
        plans_json=json.dumps(result["plans"]),
        itinerary_json=json.dumps(itinerary),
        data_label=result["data_label"],
        nights=result["nights"],
        nights_assumed=result["nights_assumed"],
        distance_km=result["distance_km"],
        notes_json=json.dumps(result.get("notes") or []),
    )
