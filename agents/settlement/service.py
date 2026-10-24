"""Settlement workflow, shared by the Settlement agent and the orchestrator's fallback path."""

import json

from agents.models import SettleRequest, SettleResponse
from agents.settlement.logic import settle


def make_settle_response(req: SettleRequest) -> SettleResponse:
    try:
        result = settle(json.loads(req.members_json), json.loads(req.payments_json))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return SettleResponse(user_address=req.user_address, error=str(exc))
    return SettleResponse(user_address=req.user_address, result_json=json.dumps(result))
