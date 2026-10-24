"""Settlement workflow, shared by the Settlement agent and the orchestrator's fallback path."""

import json

from agents.models import SettleRequest, SettleResponse
from agents.settlement.logic import settle, settle_expenses


def make_settle_response(req: SettleRequest) -> SettleResponse:
    try:
        members = json.loads(req.members_json)
        expenses = json.loads(req.expenses_json or "[]")
        if expenses:
            result = settle_expenses(members, expenses)
        else:
            result = settle(members, json.loads(req.payments_json or "{}"))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return SettleResponse(user_address=req.user_address, error=str(exc))
    return SettleResponse(user_address=req.user_address, result_json=json.dumps(result))
