"""Message contracts between the orchestrator and the worker agents.

Structured payloads travel as JSON strings so the message schemas stay flat and stable.
"""

from uagents import Model


class PlanRequest(Model):
    user_address: str
    origin: str
    destination: str
    people: int
    budget_per_person: int
    nights: int = 0  # 0 = not given; the planner picks a length that suits the distance
    date: str = ""


class PlanResponse(Model):
    user_address: str
    plans_json: str = "[]"
    itinerary_json: str = "[]"
    data_label: str = ""
    nights: int = 1
    nights_assumed: bool = False
    distance_km: int = 0
    notes_json: str = "[]"
    error: str = ""


class SettleRequest(Model):
    user_address: str
    members_json: str
    payments_json: str


class SettleResponse(Model):
    user_address: str
    result_json: str = "{}"
    error: str = ""
