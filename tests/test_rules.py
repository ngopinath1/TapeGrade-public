import copy

import pytest
from pydantic import ValidationError

from backend.api.types import Decision, Guardrails, Tracking
from backend.models.mock import MockSAM, MockSpark
from backend.providers.demo import DemoLeagueProvider
from backend.services.metrics import calculate_metrics
from backend.services.staging import validate_decision


def evidence():
    league = DemoLeagueProvider().snapshot()
    track = MockSAM().track({"player_id": "c1"}, "cream basketball jersey number 4", [])
    candidate = {
        "player": league["available"][0],
        "verified": True,
        "quality": 0.91,
        "metrics": [m.model_dump() for m in calculate_metrics(track, 0.91)],
    }
    decision = MockSpark().reason(
        "decide",
        {
            "candidates": [candidate],
            "roster": league["roster"],
            "guardrails": Guardrails().model_dump(),
        },
        Decision,
    )
    return league, candidate, decision


@pytest.mark.parametrize("bid,budget,expected", [(3, 74, 3), (12, 2, 2), (0, 74, 0)])
def test_faab_capped_by_guardrails_and_budget(bid, budget, expected):
    league, c, d = evidence()
    d.move.faab_bid = 500
    _, move = validate_decision(d, [c], league["roster"], Guardrails(max_faab_bid=bid), budget)
    assert move["faab_bid"] == expected


def test_protected_player_never_dropped():
    league, c, d = evidence()
    d.move.drop_player_id = "r1"
    _, move = validate_decision(d, [c], league["roster"], Guardrails(), 74)
    assert move is None


def test_no_video_metrics_no_add():
    league, c, d = evidence()
    d.verdicts[0].metric_refs = []
    c["metrics"] = []
    decision, move = validate_decision(d, [c], league["roster"], Guardrails(), 74)
    assert move is None and decision.verdicts[0].verdict == "MONITOR"


def test_unavailable_metric_reference_rejected():
    league, c, d = evidence()
    d.verdicts[0].metric_refs = ["shot_opportunity"]
    with pytest.raises(ValueError, match="unavailable"):
        validate_decision(d, [c], league["roster"], Guardrails(), 74)


def test_missing_tracks_are_unavailable_not_zero():
    t = Tracking(width=960, height=540, fps=12, prompt="x", frames=[], simulated=True)
    m = calculate_metrics(t, 0.9)
    assert all(x.value is None and x.unavailable_reason for x in m)


def test_missing_ball_keeps_defender_metric():
    t = MockSAM().track({"player_id": "c1"}, "refined", [])
    for f in t.frames:
        f.objects = [o for o in f.objects if o.role != "ball"]
    m = {x.name: x for x in calculate_metrics(t, 0.9)}
    assert m["defender_proximity"].value is not None
    assert m["on_ball_involvement"].value is None


def test_response_validation_rejects_invalid_enum_confidence():
    with pytest.raises(ValidationError):
        Decision.model_validate(
            {
                "verdicts": [
                    {
                        "player_id": "c1",
                        "verdict": "BUY",
                        "confidence": 1.2,
                        "rationale": "x",
                        "strengths": [],
                        "weaknesses": [],
                        "metric_refs": [],
                    }
                ],
                "move": None,
            }
        )


def test_instruction_changes_shortlist():
    from backend.agents.scout import ScoutAgent

    league = DemoLeagueProvider().snapshot()
    assert ScoutAgent(MockSpark()).shortlist(
        "Find a center for rebounds", league, 3
    ).player_ids == ["c4"]


def test_decision_agent_withholds_unsupported_model_interpretation_without_retry():
    from backend.agents.decision import DecisionAgent

    league, candidate, decision = evidence()
    decision.verdicts[0].metric_refs = ["invented_or_unavailable_metric"]

    class OneResponse:
        calls = 0

        def reason(self, *args, **kwargs):
            self.calls += 1
            return decision

    model = OneResponse()
    agent = DecisionAgent(model)
    result, move = agent.decide("Inspect the evidence", league, [candidate], Guardrails())
    assert model.calls == 1 and move is None
    assert result.verdicts[0].verdict == "MONITOR"
    assert result.verdicts[0].confidence == 0 and result.verdicts[0].metric_refs == []
    assert "withheld" in result.verdicts[0].rationale
    assert agent.validation_warnings[0]["unsupported_metric_refs"] == [
        "invented_or_unavailable_metric"
    ]
