import json

import pytest

from agents.orchestrator import replies
from agents.parsing import budget_per_person, missing_questions, parse_card_selection, parse_payments, parse_trip
from agents.data.sample_prices import build_route
from agents.planner.logic import build_plans
from agents.settlement.logic import settle


def test_parse_trip_one_liner():
    trip = parse_trip("5 of us, Delhi to Jaipur this Saturday for 1 night, ₹4,000 each.")
    assert trip["origin"] == "Delhi" and trip["destination"] == "Jaipur"
    assert trip["people"] == 5 and trip["nights"] == 1
    assert trip["budget_amount"] == 4000 and trip["budget_basis"] == "per_person"
    assert budget_per_person(trip) == 4000
    assert trip["date"] == "this saturday"
    assert missing_questions(trip) == []


def test_unstated_details_become_questions():
    trip = parse_trip("Goa trip with friends, budget 40000")
    fields = [f for f, _ in missing_questions(trip)]
    assert {"origin", "people", "date", "nights", "budget_basis"} <= set(fields)
    assert budget_per_person(trip) is None


def test_total_budget_is_divided_only_when_stated():
    trip = parse_trip("4 of us, Pune to Goa, 2 nights next month, 40k total")
    assert trip["budget_basis"] == "total" and budget_per_person(trip) == 10000


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


def _modes(result):
    return {p["transport"] for p in result["plans"]}


def test_estimates_are_labelled_and_distance_based():
    result = build_plans("Surat", "Delhi", 5, 10000)
    assert "not live" in result["data_label"]
    assert 1000 < result["distance_km"] < 1400  # Surat-Delhi is roughly 1,150 km by road


def test_long_trip_gets_more_nights_and_fits_budget():
    result = build_plans("Surat", "Delhi", 5, 10000)
    assert result["nights_assumed"] and result["nights"] >= 2
    assert result["plans"][0]["within_budget"]


def test_no_overlong_journey_on_a_short_trip():
    result = build_plans("Surat", "Delhi", 5, 10000, nights=1)
    assert all(p["travel_hours"] <= 12 for p in result["plans"])
    assert any("too slow" in n for n in result["notes"])


def test_short_trip_has_no_flight_and_long_trip_no_cab():
    assert not any("Flight" in m for m in _modes(build_plans("Delhi", "Jaipur", 5, 20000)))
    assert not any("cab" in m for m in _modes(build_plans("Surat", "Delhi", 5, 50000)))


def test_hill_rules():
    manali = build_plans("Delhi", "Manali", 6, 50000)
    assert not any("Train" in m for m in _modes(manali))
    assert any("Kullu" in m for m in _modes(manali))
    darjeeling = build_route("Kolkata", "Darjeeling")
    assert any("New Jalpaiguri" in t["name"] for t in darjeeling["transport"])


def test_too_close_is_rejected():
    with pytest.raises(ValueError):
        build_plans("Delhi", "Noida", 3, 2000)


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
