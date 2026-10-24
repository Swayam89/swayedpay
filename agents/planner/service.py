"""Planner workflow, shared by the Planner agent and the orchestrator's fallback path."""

import json

from agents import asi1
from agents.models import PlanRequest, PlanResponse
from agents.planner.logic import build_plans


async def make_plan_response(req: PlanRequest) -> PlanResponse:
    try:
        result = build_plans(req.origin, req.destination, req.people, req.budget_per_person, req.nights)
    except ValueError as exc:
        return PlanResponse(user_address=req.user_address, error=str(exc))
    itinerary = await asi1.write_itinerary(req.destination, result["nights"]) or []
    return PlanResponse(
        user_address=req.user_address,
        plans_json=json.dumps(result["plans"]),
        itinerary_json=json.dumps(itinerary),
        data_label=result["data_label"],
    )
