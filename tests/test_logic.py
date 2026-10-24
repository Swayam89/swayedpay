import json

import pytest

from agents.orchestrator import replies
from agents.parsing import missing_fields, parse_card_selection, parse_payments, parse_trip
from agents.planner.logic import build_plans
from agents.settlement.logic import settle


def test_parse_trip_one_liner():
    trip = parse_trip("5 of us, Delhi to Jaipur this Saturday, ₹4,000 each max.")
    assert trip["origin"] == "Delhi"
    assert trip["destination"] == "Jaipur"
    assert trip["people"] == 5
    assert trip["budget_per_person"] == 4000
    assert trip["date"] == "this saturday"
    assert missing_fields(trip) == []


def test_parse_trip_reports_missing():
    trip = parse_trip("Goa trip with friends")
    assert "how many people are going" in missing_fields(trip)


def test_budget_fit_keeps_comfort_when_possible():
    plans = build_plans("Delhi", "Jaipur", 5, 4000, 1)["plans"]
    best = plans[0]
    assert best["within_budget"]
    assert best["per_person"] <= 4000
    assert best["swaps"], "the budget check should explain its swaps"
    # The fitted plan should never be cheaper than the cheapest option it offers.
    assert best["per_person"] >= min(p["per_person"] for p in plans)


def test_nothing_fits_is_labelled():
    plans = build_plans("Delhi", "Jaipur", 5, 1000, 1)["plans"]
    assert not any(p["within_budget"] for p in plans)
    assert plans[0]["name"] == "Closest to your budget"


def test_unknown_route_uses_labelled_generic_data():
    result = build_plans("Pune", "Hampi", 3, 6000, 2)
    assert "generic" in result["data_label"].lower()


def test_settle_matches_deck_example():
    result = settle(["Aman", "Rahul", "Dev", "Isha", "Kabir"], {"Aman": 9000, "Rahul": 4250})
    assert result["total"] == 13250
    assert result["shares"]["Dev"] == 2650
    owed = {(t["from"], t["to"]): t["amount"] for t in result["transfers"]}
    assert sum(t["amount"] for t in result["transfers"] if t["to"] == "Aman") == 6350
    assert sum(t["amount"] for t in result["transfers"] if t["to"] == "Rahul") == 1600
    assert len(owed) == 4


def test_settle_uneven_total_adds_up():
    result = settle(["A", "B", "C"], {"A": 100})
    assert sum(result["shares"].values()) == 100
    assert sum(t["amount"] for t in result["transfers"]) == 100 - result["shares"]["A"]


def test_settle_rejects_no_payments():
    with pytest.raises(ValueError):
        settle(["A", "B"], {})


def test_parse_payments_and_selection():
    data = parse_payments("Aman, Rahul, Dev, Isha, Kabir. Aman paid 9000, Rahul paid 4,250.")
    assert data["payments"] == {"Aman": 9000, "Rahul": 4250}
    assert data["members"] == ["Aman", "Rahul", "Dev", "Isha", "Kabir"]
    assert parse_card_selection('{"action": "choose_plan", "plan_id": "b"}') == {"action": "choose_plan", "plan_id": "B"}
    assert parse_card_selection("The user picked plan_id A from the card") == {"action": "choose_plan", "plan_id": "A"}
    assert parse_card_selection("c") == {"action": "choose_plan", "plan_id": "C"}
    assert parse_card_selection('{"action": "new_trip"}') == {"action": "new_trip"}


def test_cards_are_valid_and_small():
    trip = {"origin": "Delhi", "destination": "Jaipur", "people": 5, "budget_per_person": 4000, "nights": 1}
    plans = build_plans("Delhi", "Jaipur", 5, 4000, 1)["plans"]
    msg = replies.message("x", card=replies.plans_card(trip, plans))
    meta = msg.content[1].metadata
    assert meta["card_protocol_version"] == "1"
    assert all(isinstance(v, str) for v in meta.values())
    assert len(meta["card_payload"].encode()) < 64 * 1024
    json.loads(meta["card_payload"])
