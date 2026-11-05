"""Synthetic unit inputs exercise transaction constraints without fantasy actions."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from backend.api.types import Decision, Guardrails
from backend.services.staging import validate_decision, position_feasible
from backend.services.stat_enrichment import fingerprint
from tests.test_statistics import sample_league, connect_batch, batch
from backend.services.state import get_league, save_league
from backend.db.database import session_scope
from backend.db.schema import League, ScanRun, StatsRefresh
from backend.worker.scan import enqueue
from backend.models.base import ModelError


def inputs():
    l = sample_league()
    l["scouting_ready"] = True
    l["fetched_at"] = datetime.now(timezone.utc).isoformat()
    for p in l["roster"] + l["available"]:
        p["recent"] = {
            "ready": True,
            "provider": "unit_fixture",
            "window_start": "2026-10-06",
            "window_end": "2026-11-04",
            "scoring_fingerprint": fingerprint(l),
            "refresh_id": "synthetic-unit-fixture",
        }
    add, drop = l["available"][0], l["roster"][0]
    l["eligibility_reviews"] = {
        p["id"]: {
            "acquisition": "free_agent" if p == add else "unknown",
            "drop_allowed": p == drop,
            "reviewed_at": l["fetched_at"],
            "fingerprint": fingerprint(l),
        }
        for p in [add, drop]
    }
    c = {
        "player": add,
        "verified": True,
        "quality": 0.9,
        "metrics": [{"name": "defender_proximity", "value": 5, "evidence_frames": [0, 6]}],
    }
    d = Decision.model_validate(
        {
            "verdicts": [
                {
                    "player_id": add["id"],
                    "verdict": "ADD",
                    "confidence": 0.9,
                    "rationale": "Synthetic unit fixture",
                    "strengths": [],
                    "weaknesses": [],
                    "metric_refs": ["defender_proximity"],
                }
            ],
            "move": {
                "add_player_id": add["id"],
                "drop_player_id": drop["id"],
                "faab_bid": 9,
                "reasoning": "Synthetic unit fixture",
            },
        }
    )
    return l, c, d


def test_non_faab_never_invents_bid():
    l, c, d = inputs()
    _, m = validate_decision(d, [c], l["roster"], Guardrails(protected_players=[]), None, league=l)
    assert m is not None and m["faab_bid"] is None and not m["executed"]


@pytest.mark.parametrize("budget,expected", [(None, None), (0, 0), (3, 3)])
def test_faab_requires_current_budget(budget, expected):
    l, c, d = inputs()
    l["rules"]["waiver_mode"] = "faab"
    l["eligibility_reviews"][c["player"]["id"]]["acquisition"] = "waivers"
    _, m = validate_decision(
        d, [c], l["roster"], Guardrails(protected_players=[]), budget, league=l
    )
    assert m is None if expected is None else m["faab_bid"] == expected


@pytest.mark.parametrize(
    "issue",
    [
        "protected",
        "locked",
        "stale",
        "not_available",
        "position",
        "changed_stats",
        "wrong_window",
        "rules_changed",
        "adds_disabled",
    ],
)
def test_real_move_fails_closed(issue):
    l, c, d = inputs()
    g = Guardrails(protected_players=[])
    if issue == "protected":
        g.protected_players = [l["roster"][0]["id"]]
    elif issue == "locked":
        l["eligibility_reviews"][l["roster"][0]["id"]]["drop_allowed"] = False
    elif issue == "stale":
        l["fetched_at"] = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    elif issue == "not_available":
        l["available"] = []
    elif issue == "position":
        l["roster_positions"] = ["C"]
        l["rules"]["fingerprint"] = fingerprint(l)
    elif issue == "changed_stats":
        l["available"] = [deepcopy(c["player"])]
        l["available"][0]["recent"]["refresh_id"] = "new-snapshot"
    elif issue == "wrong_window":
        l["roster"][0]["recent"]["window_start"] = "2026-10-20"
    elif issue == "rules_changed":
        l["scoring"]["weights"]["pts"] = 2
    elif issue == "adds_disabled":
        l["rule_settings"]["disable_adds"] = 1
    _, move = validate_decision(d, [c], l["roster"], g, None, league=l)
    assert move is None


def test_flexible_slots_have_matching_not_simple_position_equality():
    players = [{"positions": ["PG"]}, {"positions": ["PG", "SG"]}, {"positions": ["C"]}]
    assert position_feasible(players, ["G", "SG", "UTIL"])
    assert not position_feasible(players, ["G", "SG"])


def test_review_api_workspace_selector_and_no_model_spend(client, store):
    l, rid = connect_batch(store)
    response = client.post(
        "/api/scans", json={"instruction": "Find a guard", "league_id": "demo-nba"}
    )
    assert response.status_code == 409
    assert client.post("/api/scans", json={"instruction": "Find a guard"}).status_code == 409
    assert client.get("/api/stats").json()["jobs"][0]["status"] == "COMPLETED"
    assert (
        client.post(
            "/api/stats/mappings",
            json={
                "sleeper_id": "2",
                "athlete_id": "wrong",
                "source_ref": "offline:synthetic-review",
            },
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/league/rules",
            json={
                "game_mode": "game_pick",
                "waiver_mode": "priority",
                "point_bonus_mode": "unknown",
                "source_ref": "offline:synthetic-review",
            },
        ).status_code
        == 200
    )
    assert (
        client.put("/api/settings", json=Guardrails(protected_players=[]).model_dump()).status_code
        == 200
    )
    assert get_league(store)["protections_reviewed"]
    assert client.post("/api/stats/refresh").status_code == 409
    with session_scope(store) as s:
        assert not s.query(ScanRun).count()


def test_refresh_preserves_evidence_and_invalidates_rules_on_change(store):
    l, rid = connect_batch(store)
    fresh = deepcopy(l)
    fresh["rule_settings"]["leg"] = 4
    save_league(fresh, store)
    assert get_league(store)["rules"]["game_mode"] == "lock_in"
    fresh["scoring"]["weights"]["pts"] = 4
    save_league(fresh, store)
    assert get_league(store)["rules"] == {}
    assert get_league(store)["roster"][0]["recent"]["refresh_id"] == rid


def test_preflight_unknown_eligibility_allows_report_without_model_calls(store, monkeypatch):
    from backend.config import settings
    from backend.services.clips import prepare_clip
    from backend.services.sample import ensure_sample
    from backend.worker import scan

    connect_batch(store)
    league, candidate, decision = inputs()
    league["eligibility_reviews"] = {}
    monkeypatch.setattr(scan, "get_league", lambda factory=None, league_id=None: deepcopy(league))
    monkeypatch.setattr(settings, "mock_models", False)
    prepare_clip(ensure_sample("c1"), league["available"][0]["id"], False, store)
    sid = scan.enqueue("Inspect a guard", factory=store)
    with session_scope(store) as s:
        row = s.get(ScanRun, sid)
        assert row.stage == "QUEUED" and row.live_calls == 0
        assert row.checkpoint["league"]["available"][0]["eligible_drop_ids"] == []
        assert row.checkpoint["league"]["scan_readiness"]["notice"].startswith(
            "Scouting report only"
        )


@pytest.mark.parametrize("with_move", [True, False])
def test_report_only_never_emits_add_even_if_model_omits_move(with_move):
    league, candidate, decision = inputs()
    league["eligibility_reviews"] = {}
    if not with_move:
        decision.move = None
    decision, move = validate_decision(
        decision,
        [candidate],
        league["roster"],
        Guardrails(protected_players=[]),
        100,
        league=league,
    )
    assert move is None and decision.move is None
    assert decision.verdicts[0].verdict == "MONITOR"
    assert any("eligibility review" in reason for reason in decision.verdicts[0].weaknesses)


def test_saved_connection_refreshes_with_new_provider_and_preserves_reviews(
    client, store, monkeypatch
):
    from backend.api import routes

    league, _ = connect_batch(store)
    connection = {"username": "unit-scout", "user_id": "7", "league_id": "123"}
    with session_scope(store) as s:
        row = s.get(League, league["id"])
        row.data = {**row.data, "connection": connection}
    created, closed = [], []

    class FreshProvider:
        def __init__(self):
            created.append(self)
            self.client = self

        def snapshot_for(self, user, league_id):
            assert user == {"user_id": "7", "username": "unit-scout"}
            assert league_id == "123"
            return {
                **deepcopy(league),
                "connection": connection,
                "fetched_at": "2026-11-04T10:00:00+00:00",
            }

        def close(self):
            closed.append(self)

    monkeypatch.setattr(routes, "SleeperLeagueProvider", FreshProvider)
    response = client.post("/api/sleeper/refresh")
    assert response.status_code == 200
    assert len(created) == 1 and closed == created
    assert get_league(store)["fetched_at"] == "2026-11-04T10:00:00+00:00"
    assert get_league(store)["rules"]["game_mode"] == "lock_in"


def test_protections_are_optional_and_never_gate_data_readiness(store):
    from backend.services.stat_enrichment import enrich_snapshot

    league = sample_league()
    league["protections_reviewed"] = False
    enriched = enrich_snapshot(league, store)
    assert enriched["protection_policy"] == "statistics_with_user_overrides"
    assert all("protect" not in reason.lower() for reason in enriched["readiness_reasons"])
    assert enriched["scouting_ready"] is False  # statistics still unavailable


def test_confirmed_faab_budget_must_match_reported_season_budget(client, store):
    league, rid = connect_batch(store)
    with session_scope(store) as s:
        row = s.get(League, league["id"])
        row.data = {
            **row.data,
            "rule_settings": {**row.data["rule_settings"], "waiver_budget": 100},
        }
    value = dict(
        game_mode="lock_in",
        waiver_mode="faab",
        point_bonus_mode="stack",
        faab_budget=100,
        source_ref="offline:owner-confirmation",
    )
    assert client.put("/api/league/rules", json=value).status_code == 200
    assert get_league(store)["rules"]["faab_budget"] == 100
    value["faab_budget"] = 200
    assert client.put("/api/league/rules", json=value).status_code == 409
    assert get_league(store)["rules"]["faab_budget"] == 100


def test_sleeper_scoring_progress_does_not_invalidate_confirmed_rules(store):
    league, rid = connect_batch(store)
    refreshed = deepcopy(league)
    refreshed["rule_settings"]["last_scored_leg"] = 2
    save_league(refreshed, store)
    assert get_league(store)["rules"]["game_mode"] == "lock_in"
