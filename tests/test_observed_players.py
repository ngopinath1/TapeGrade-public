"""Synthetic joins and player-owned evidence; no external calls."""

from copy import deepcopy
from datetime import timedelta

import pytest

from backend.agents.decision import DecisionAgent
from backend.api.types import Decision, Guardrails
from backend.db.database import session_scope
from backend.db.schema import StatsRefresh
from backend.providers.stats_base import Athlete, BoxScore, GameRecord, StatsBatch
from backend.services.observed_players import (
    add_observed_candidates,
    apply_profile_verdicts,
    build_player_profiles,
    player_pool,
)
from backend.services.stat_enrichment import enrich_snapshot, fingerprint, persist_batch
from backend.services.state import save_league
from tests.test_statistics import NOW, sample_league


@pytest.fixture
def observed(store):
    league = sample_league()
    names = [
        ("1", "Roster Player", "NYK", "9"),
        ("2", "Sam Hauser", "BOS", "30"),
        ("3", "Franz Wagner", "ORL", "22"),
        ("4", "Jamal Cain", "ORL", "8"),
    ]
    athletes, players, games = [], [], []
    for pid, name, team, number in names:
        aid = f"00000000-0000-0000-0000-{int(pid):012d}"
        athletes.append(Athlete(id=aid, name=name, team=team, jersey=number, sportradar_id=aid))
        players.append(
            {
                "id": f"sleeper:fixture:{pid}",
                "external_id": pid,
                "name": name,
                "team": team,
                "number": int(number),
                "positions": ["PG"],
                "is_demo": False,
                "sportradar_id": aid,
                "nba_id": None,
            }
        )
        for day in range(3):
            games.append(
                GameRecord(
                    provider="fixture",
                    athlete_id=aid,
                    game_id=f"game-{day}",
                    game_date=(NOW - timedelta(days=4 - day)).date(),
                    season=2026,
                    status="final",
                    participation="played",
                    minutes=20.0,
                    stats=BoxScore(pts=int(pid) * 5, reb=2, ast=1, stl=0, blk=0, to=1, tpm=1),
                    fetched_at=NOW,
                    source_ref=f"offline:boxscore:{day}",
                    synthetic=False,
                )
            )
    league.update(
        roster=[players[0]],
        available=[players[1], players[3]],
        other_rostered=[players[2]],
        scoring={
            "type": "points",
            "weights": {"pts": 1, "reb": 1, "ast": 1, "stl": 1, "blk": 1, "to": -1, "tpm": 0.5},
        },
    )
    league["rules"]["fingerprint"] = fingerprint(league)
    save_league(league, store)
    batch = StatsBatch(
        provider="fixture",
        start_date=(NOW - timedelta(days=7)).date(),
        end_date=NOW.date(),
        fetched_at=NOW,
        complete=True,
        source_ref="offline:batch",
        athletes=athletes,
        games=games,
        synthetic=False,
    )
    with session_scope(store) as s:
        summary = persist_batch(s, batch, league)
        row = StatsRefresh(league_id=league["id"], status="COMPLETED", data={"summary": summary})
        s.add(row)
        s.flush()
        rid = row.id
    league = enrich_snapshot(league, store, NOW)
    league["film_player_pool"] = player_pool(league)
    roster = [
        {"espn_id": str(i), "name": name, "team": team, "jersey_number": number}
        for i, (_, name, team, number) in enumerate(names[1:], 100)
    ]
    bindings = [
        {"object_id": i + 1, "role": "target" if i == 0 else "defender", **p}
        for i, p in enumerate(roster)
    ]
    tracking = {
        "width": 100,
        "height": 100,
        "fps": 12,
        "prompt": "offline fixture",
        "simulated": False,
        "frames": [
            {
                "frame": f,
                "time": f / 12,
                "objects": [
                    {
                        "id": i + 1,
                        "role": "target" if i == 0 else "defender",
                        "box": [x, 10, x + 5, 40],
                        "centroid": [x, 20],
                    }
                    for i, x in enumerate([10, 60, 70])
                ],
            }
            for f in range(4)
        ],
    }
    candidate = {
        "player": league["available"][0],
        "clip": {
            "id": "synthetic-clip",
            "source_ref": "https://example.test/clip",
            "game_date": "2026-11-01",
            "source_identity": {
                "version": 2,
                "roster_match": True,
                "source_ref": "https://example.test/roster",
                "roster": roster,
            },
        },
        "identity": {"status": "corroborated", "tracked_players": bindings},
        "tracking": tracking,
        "quality": 0.9,
        "verified": True,
        "critiques": [
            {
                "target_identity_preserved": True,
                "team_roles_preserved": True,
                "role_conflicts": [],
                "player_identity_checks": [
                    {"object_id": i, "identity_preserved": True, "reason": "Offline fixture"}
                    for i in [1, 2, 3]
                ],
            }
        ],
        "metrics": [],
        "overlays": [],
    }
    assert candidate["player"]["recent"]["refresh_id"] == rid
    return candidate, league, rid


def test_profiles_have_separate_scores_membership_and_opponent_only_distances(store, observed):
    c, l, _ = observed
    profiles = build_player_profiles(c, l, store, NOW)
    assert [p["name"] for p in profiles] == ["Sam Hauser", "Franz Wagner", "Jamal Cain"]
    assert [p["statistics"]["averages"]["pts"]["value"] for p in profiles] == [10, 15, 20]
    assert [p["availability"] for p in profiles] == ["available", "rostered_elsewhere", "available"]
    assert all(p["statistics"]["sample_size"] == 3 and p["statistics"]["ready"] for p in profiles)
    assert profiles[1]["recommendation"]["verdict"] == "TRADE_RESEARCH"
    assert profiles[1]["film"]["metrics"][0]["value"] == 50  # excludes ORL teammate 10px away
    assert profiles[2]["film"]["metrics"][0]["value"] == 60


def test_failed_opponent_track_cannot_influence_another_players_measurements(store, observed):
    c, l, _ = observed
    c["critiques"][0]["player_identity_checks"][1]["identity_preserved"] = False
    profiles = build_player_profiles(c, l, store, NOW)
    assert profiles[0]["film"]["metrics"][0]["value"] == 60
    assert profiles[0]["film"]["trusted_object_ids"] == [1, 3]
    assert not profiles[1]["film"]["accepted"]
    assert all(m["value"] is None for m in profiles[1]["film"]["metrics"])


def test_selecting_an_observed_player_rescopes_reviewed_overlay_roles(store, observed):
    c, league, _ = observed
    c["reviewed_tracking"] = deepcopy(c["tracking"])
    c["tracking_review"] = {
        "scene_only": False,
        "target_quality": 0.9,
        "trusted_object_ids": [1, 2, 3],
        "quality_by_id": {"1": 0.9, "2": 0.9, "3": 0.9},
        "issues": [],
        "roles": {"target": 1, "defender": 2, "ball": 0, "unknown": 0},
    }
    c["identified_players"] = build_player_profiles(c, league, store, NOW)
    related = add_observed_candidates([c], league, Guardrails(protected_players=[]))[1]
    assert related["player"]["name"] == "Jamal Cain"
    roles = {o["id"]: o["role"] for o in related["reviewed_tracking"]["frames"][0]["objects"]}
    assert roles[3] == "target" and roles[1] == "defender"
    assert 2 not in roles  # A teammate of the selected player is not a defender.


@pytest.mark.parametrize(
    "fault",
    ["jersey", "duplicate", "game_date", "unreadable", "shared_id_conflict", "missing_batch"],
)
def test_conflicting_joins_never_guess(store, observed, fault):
    c, l, rid = deepcopy(observed)
    if fault == "game_date":
        c["clip"]["game_date"] = "2026-10-01"
    if fault == "unreadable":
        c["identity"]["tracked_players"][2]["name"] = None
    if fault == "shared_id_conflict":
        next(p for p in l["film_player_pool"] if p["name"] == "Jamal Cain")["nba_id"] = "wrong"
    with session_scope(store) as s:
        r = s.get(StatsRefresh, rid)
        data = deepcopy(r.data)
        if fault == "jersey":
            data["summary"]["athletes"][3]["jersey"] = "99"
        if fault == "duplicate":
            data["summary"]["athletes"].append(
                {**data["summary"]["athletes"][3], "id": "another-id"}
            )
        if fault == "shared_id_conflict":
            data["summary"]["athletes"][3]["nba_id"] = "right"
        if fault == "missing_batch":
            c["player"]["recent"]["refresh_id"] = "missing"
        r.data = data
    cain = next(
        (p for p in build_player_profiles(c, l, store, NOW) if p["name"] == "Jamal Cain"), None
    )
    if fault == "unreadable":
        assert cain is None
    elif fault == "shared_id_conflict":
        assert cain["league_player_id"] is None and cain["availability"] == "unknown"
    else:
        assert cain["statistics"] is None and cain["match_status"] == "stats_unmatched"


@pytest.mark.parametrize(
    "fault", ["low_quality", "missing_check", "failed_check", "stale", "synthetic", "incomplete"]
)
def test_each_player_needs_their_own_reliable_evidence(store, observed, fault):
    c, l, rid = deepcopy(observed)
    clock = NOW
    if fault == "low_quality":
        c["quality"] = 0.45
    if fault == "missing_check":
        c["critiques"][0]["player_identity_checks"] = []
    if fault == "failed_check":
        c["critiques"][0]["player_identity_checks"][2]["identity_preserved"] = False
    if fault == "stale":
        clock += timedelta(days=2)
    if fault in {"synthetic", "incomplete"}:
        with session_scope(store) as s:
            r = s.get(StatsRefresh, rid)
            data = deepcopy(r.data)
            data["summary"]["synthetic" if fault == "synthetic" else "complete"] = (
                fault == "synthetic"
            )
            r.data = data
    profiles = build_player_profiles(c, l, store, clock)
    c["identified_players"] = profiles
    assert len(add_observed_candidates([c], l, Guardrails(protected_players=[]))) == 1
    cain = profiles[2]
    assert cain["recommendation"]["verdict"] in {"MONITOR", "MORE_DATA"}
    if fault in {"low_quality", "missing_check", "failed_check"}:
        assert not cain["film"]["accepted"]
        assert all(m["value"] is None for m in cain["film"]["metrics"])


def test_available_accepted_players_share_one_decision_call_and_keep_separate_evidence(
    store, observed
):
    c, l, _ = observed
    c["identified_players"] = build_player_profiles(c, l, store, NOW)
    c["metrics"] = c["identified_players"][0]["film"]["metrics"]
    candidates = add_observed_candidates([c], l, Guardrails(protected_players=[]))
    assert [p["player"]["name"] for p in candidates] == ["Sam Hauser", "Jamal Cain"]
    assert candidates[1]["tracking"]["frames"][0]["objects"][-1]["role"] == "target"

    class Spark:
        calls = 0

        def reason(self, op, payload, schema):
            self.calls += 1
            assert op == "decide" and len(payload["candidates"]) == 2
            assert [x["metrics"][0]["value"] for x in payload["candidates"]] == [50, 60]
            assert all(len(x["identified_players"]) == 3 for x in payload["candidates"])
            return Decision(
                verdicts=[
                    {
                        "player_id": x["player"]["id"],
                        "verdict": "ADD",
                        "confidence": 0.9,
                        "rationale": "Offline review",
                        "strengths": [],
                        "weaknesses": [],
                        "metric_refs": ["defender_proximity"],
                    }
                    for x in payload["candidates"]
                ],
                move=None,
            )

    spark = Spark()
    decision, move = DecisionAgent(spark).decide(
        "Find useful players", l, candidates, Guardrails(protected_players=[])
    )
    assert spark.calls == 1 and move is None
    assert all(
        v.verdict == "MONITOR" for v in decision.verdicts
    )  # missing lock/availability reviews
    for candidate, verdict in zip(candidates, decision.verdicts):
        candidate["verdict"] = verdict.model_dump()
    apply_profile_verdicts(candidates)
    assert (
        candidates[0]["identified_players"][2]["recommendation"]["source"]
        == "model_with_guardrails"
    )
    assert len(add_observed_candidates(candidates, l, Guardrails(protected_players=[]))) == 2
