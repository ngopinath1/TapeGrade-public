"""All statistics here are synthetic contract fixtures, never live NBA evidence."""

from datetime import date, datetime, timedelta, timezone
from copy import deepcopy
import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, func
from backend.api.types import Criticism, Guardrails
from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import GameLog, League, StatsRefresh
from backend.models.sam import corrected_prompt
from backend.models.base import ModelError
from backend.providers.base import ScoringEngine
from backend.providers.stats_base import Athlete, BoxScore, GameRecord, StatsBatch
from backend.providers.stats_balldontlie import BallDontLieStatsProvider, StatsProviderError
from backend.services.player_identity import normalized_name, propose_matches, save_identity
from backend.services.stat_enrichment import enrich_snapshot, fingerprint
from backend.services.state import save_league
from backend.worker.stats import enqueue_refresh, run_once

NOW = datetime(2026, 11, 4, 17, tzinfo=timezone.utc)


def sample_league():
    def player(pid, name):
        return dict(
            id="sleeper:fixture:" + pid,
            external_id=pid,
            name=name,
            team="NYK",
            positions=["PG"],
            is_demo=False,
            fantasy_points=195 if pid == "1" else None,
            minutes=None,
            previous_minutes=None,
            trend=[],
            stats={},
        )

    league = dict(
        id="sleeper:fixture",
        name="SYNTHETIC contract league",
        provider="sleeper",
        season="2026",
        is_demo=False,
        scoring={
            "type": "points",
            "weights": {
                "pts": 0.5,
                "reb": 1,
                "ast": 1,
                "stl": 2,
                "blk": 2,
                "to": -1,
                "tpm": 0.5,
                "dd": 1,
                "td": 2,
                "bonus_pt_40p": 2,
                "bonus_pt_50p": 2,
                "tf": -2,
                "ff": -2,
            },
        },
        rule_settings={"game_mode": 1, "waiver_type": 0, "disable_adds": 0},
        roster_positions=["PG"],
        roster=[player("1", "Fixture Roster")],
        available=[player("2", "Fixture Candidate")],
        faab_remaining=None,
        protections_reviewed=True,
        guardrails=Guardrails(protected_players=[]).model_dump(),
        fetched_at=NOW.isoformat(),
    )
    league["rules"] = {
        "game_mode": "lock_in",
        "waiver_mode": "priority",
        "point_bonus_mode": "stack",
        "fingerprint": fingerprint(league),
    }
    return league


def batch(at=NOW, count=5, missing=False):
    games = []
    for aid in ["101", "102"]:
        for i in range(count):
            stats = dict(pts=20 + i, reb=10, ast=10, stl=1, blk=0, to=2, tpm=2, tf=0, ff=0)
            if missing:
                stats.pop("tf")
            games.append(
                GameRecord(
                    provider="fixture",
                    athlete_id=aid,
                    game_id=str(i),
                    game_date=(at - timedelta(days=count - i)).date(),
                    season=2026,
                    status="final",
                    participation="played",
                    minutes=20 + i,
                    stats=BoxScore(**stats),
                    fetched_at=at,
                    source_ref="offline:synthetic-game-log",
                    synthetic=True,
                )
            )
    return StatsBatch(
        provider="fixture",
        start_date=(at - timedelta(days=29)).date(),
        end_date=at.date(),
        fetched_at=at,
        complete=True,
        source_ref="offline:synthetic-contract-fixture",
        synthetic=True,
        athletes=[
            Athlete(id="101", name="Fixture Roster", team="NYK"),
            Athlete(id="102", name="Fixture Candidate", team="NYK"),
        ],
        games=games,
    )


def connect_batch(store, value=None):
    league = sample_league()
    save_league(league, store)
    with session_scope(store) as s:
        row = s.get(League, league["id"])
        row.data = league
        for sid, aid in [("1", "101"), ("2", "102")]:
            save_identity(
                s, sid, "fixture", aid, {"verified": True, "source_ref": "offline:identity-review"}
            )
    rid = enqueue_refresh(league, value or batch(), store)
    assert run_once(store)
    return league, rid


def test_local_scoring_recalculates_live_averages_and_survives_roster_refresh(client, store):
    from backend.services.state import get_league

    original, _ = connect_batch(store)
    before = client.get("/api/bootstrap").json()
    saved = {
        **before["settings"],
        "scoring_weights": {**before["league"]["scoring"]["weights"], "pts": 2},
    }
    assert client.put("/api/settings", json=saved).status_code == 200
    after = client.get("/api/bootstrap").json()["league"]
    assert after["roster"][0]["fantasy_points"] == 195
    assert (
        after["roster"][0]["recent_fantasy_average"]
        == before["league"]["roster"][0]["recent_fantasy_average"] + 33
    )
    assert after["rules"]["game_mode"] == "lock_in"
    save_league(original, store)
    refreshed = get_league(store)
    assert refreshed["scoring"]["weights"]["pts"] == 2
    assert refreshed["rules"]["game_mode"] == "lock_in"


@pytest.mark.parametrize("points,bonus", [(39, 0), (40, 2), (49, 2), (50, 4), (60, 4)])
def test_per_game_bonus_stacking(points, bonus):
    stats = dict(pts=points, reb=10, ast=10, stl=0, blk=0)
    assert (
        ScoringEngine().score(
            stats,
            {"dd": 1, "td": 2, "bonus_pt_40p": 2, "bonus_pt_50p": 2},
            {"point_bonus_mode": "stack"},
        )
        == 3 + bonus
    )


def test_bonus_modes_missing_fields_and_weight_zero():
    e = ScoringEngine()
    assert (
        e.score(
            {"pts": 50},
            {"bonus_pt_40p": 2, "bonus_pt_50p": 2},
            {"point_bonus_mode": "highest_only"},
        )
        == 2
    )
    assert e.score({"pts": 50}, {"bonus_pt_40p": 2}) is None
    assert e.score({"pts": 0}, {"pts": 1, "tf": 0}) == 0
    assert e.score({"pts": 20, "pf": 3}, {"pts": 1, "tf": -2}) is None
    assert e.score({"pts": 20, "dd": 1}, {"dd": 1}) is None
    assert e.score({"pts": 20}, {"unknown_rule": 1}) is None
    assert e.score({"pts": float("nan")}, {"pts": 1}) is None
    assert (
        e.score(
            {"turnover": 3, "fg3m": 2, "fg3a": 5, "fgm": 4, "fga": 10, "ftm": 3, "fta": 4},
            {"to": -1, "tpm": 1, "tpmi": -1, "fgmi": -1, "ftmi": -1},
        )
        == -11
    )


@pytest.mark.parametrize(
    "raw",
    [dict(pts=-1), dict(tf=False), dict(tf=1.5), dict(fgm=3, fga=2), dict(reb=10, oreb=3, dreb=8)],
)
def test_invalid_box_scores(raw):
    with pytest.raises(ValidationError):
        BoxScore(**raw)


def test_import_consistency():
    b = batch().model_dump(mode="json")
    b["games"][0]["athlete_id"] = "unknown"
    with pytest.raises(ValidationError):
        StatsBatch.model_validate(b)
    b = batch().model_dump(mode="json")
    b["games"][0]["synthetic"] = False
    with pytest.raises(ValidationError):
        StatsBatch.model_validate(b)


def test_identity_collisions_suffixes_and_transfers():
    players = [
        {"id": "p1", "external_id": "1", "name": "Gary Trent Jr.", "team": "OLD"},
        {"id": "p2", "external_id": "2", "name": "Unknown Athlete"},
    ]
    athletes = [Athlete(id="7", name="Gary Trent", team="NEW")]
    assert normalized_name("Kristaps Porziņģis") == "kristaps porzingis"
    assert [p["status"] for p in propose_matches(players, athletes)] == ["review", "unmatched"]
    assert (
        propose_matches(players, athletes + [Athlete(id="8", name="Gary Trent Jr.")])[0]["status"]
        == "ambiguous"
    )
    players.append({"id": "p3", "external_id": "3", "name": "Gary Trent"})
    assert all(
        p["status"] == "ambiguous" for p in propose_matches(players, athletes) if p["matches"]
    )


def test_shared_ids_and_conflicts(store):
    p = {"id": "p", "external_id": "1", "name": "Fixture Player", "nba_id": "123"}
    assert (
        propose_matches([p], [Athlete(id="x", name="Different Name", nba_id="123")])[0]["status"]
        == "verified"
    )
    with session_scope(store) as s:
        save_identity(s, "1", "fixture", "x", {"verified": True, "source_ref": "offline:shared-id"})
        s.flush()
        with pytest.raises(ValueError, match="conflict"):
            save_identity(
                s, "2", "fixture", "x", {"verified": True, "source_ref": "offline:review"}
            )


def test_synthetic_never_live_and_period_vs_average(store):
    league, rid = connect_batch(store)
    e = enrich_snapshot(league, store, NOW)
    p = e["roster"][0]
    assert not e["scouting_ready"] and not p["recent"]["ready"]
    assert p["fantasy_points"] == 195 and p["recent_fantasy_average"] == 35
    assert p["recent"]["sample_size"] == 5 and len(p["recent"]["games"]) == 5
    assert "Synthetic" in " ".join(e["readiness_reasons"])


def test_duplicate_upsert_and_correction(store):
    league, rid = connect_batch(store)
    value = batch(at=NOW + timedelta(minutes=1))
    value.games[0].stats.pts = 99
    enqueue_refresh(league, value, store)
    assert run_once(store)
    enqueue_refresh(league, batch(), store)
    assert run_once(store)
    with session_scope(store) as s:
        assert s.scalar(select(func.count()).select_from(GameLog)) == 10
        row = s.scalar(
            select(GameLog).where(GameLog.provider_player_id == "101", GameLog.game_id == "0")
        )
        assert row.data["stats"]["pts"] == 99


def test_short_samples_dnp_pending_missing_and_stale(store):
    league, rid = connect_batch(store, batch(count=3, missing=True))
    p = enrich_snapshot(league, store, NOW)["available"][0]
    assert p["recent"]["sample_size"] == 3 and p["previous_minutes"] is None
    assert p["recent_fantasy_average"] is None and any("tf" in r for r in p["recent"]["reasons"])
    value = batch(count=3)
    value.games[0].participation = "dnp"
    value.games[1].status = "in_progress"
    enqueue_refresh(league, value, store)
    run_once(store)
    e = enrich_snapshot(league, store, NOW + timedelta(days=2))
    assert e["roster"][0]["recent"]["sample_size"] == 1
    assert any("stale" in r for r in e["readiness_reasons"])


def test_incomplete_refresh_preserves_last_snapshot(store):
    league, rid = connect_batch(store)
    bad = batch()
    bad.complete = False
    failed = enqueue_refresh(league, bad, store)
    run_once(store)
    e = enrich_snapshot(league, store, NOW)
    assert (
        e["roster"][0]["recent"]["refresh_id"] == rid and e["stats_refresh"]["status"] == "FAILED"
    )


def bdl_row():
    return {
        "id": 1,
        "player": {"id": 5, "first_name": "Fixture", "last_name": "Athlete"},
        "team": {"abbreviation": "NYK"},
        "game": {"id": 8, "date": "2026-11-01", "season": 2026, "status": "Final"},
        "min": "30:30",
        "pts": 20,
        "reb": 10,
        "ast": 10,
        "stl": 1,
        "blk": 0,
        "turnover": 2,
        "fg3m": 3,
        "pf": 4,
    }


def test_bdl_pagination_cache_and_missing_fouls(store, monkeypatch):
    monkeypatch.setattr(settings, "balldontlie_api_key", SecretStr("offline-key"))
    calls = []

    def handler(request):
        calls.append(request)
        row = bdl_row()
        row["game"]["id"] = len(calls)
        return httpx.Response(
            200, json={"data": [row], "meta": {"next_cursor": 8 if len(calls) == 1 else None}}
        )

    out = BallDontLieStatsProvider(httpx.Client(transport=httpx.MockTransport(handler))).fetch(
        date(2026, 10, 6), date(2026, 11, 4), 2026
    )
    assert len(out.games) == 2 and len(out.athletes) == 1 and out.complete
    assert (
        calls[0].url.params["seasons[]"] == "2026"
        and calls[0].url.params["season_type"] == "regular"
    )
    assert calls[1].url.params["cursor"] == "8"
    assert (
        out.games[0].stats.tf is None
        and out.games[0].stats.ff is None
        and out.games[0].stats.pf == 4
    )
    assert out.games[0].minutes == 30.5 and out.games[0].source_ref.startswith("cache:stats/")


@pytest.mark.parametrize(
    "status,message", [(429, "rate limit"), (401, "access denied"), (503, "unavailable")]
)
def test_bdl_sanitized_no_retry(store, monkeypatch, status, message):
    monkeypatch.setattr(settings, "balldontlie_api_key", SecretStr("do-not-print-this"))
    count = []

    def handler(r):
        count.append(r)
        return httpx.Response(status, text="do-not-print-this", headers={"Retry-After": "60"})

    with pytest.raises(StatsProviderError, match=message) as error:
        BallDontLieStatsProvider(httpx.Client(transport=httpx.MockTransport(handler))).fetch(
            date(2026, 10, 6), date(2026, 11, 4), 2026
        )
    assert len(count) == 1 and "do-not-print-this" not in str(error.value)


def test_bdl_page_cap_and_cursor_loop(store, monkeypatch):
    monkeypatch.setattr(settings, "balldontlie_api_key", SecretStr("offline"))
    monkeypatch.setattr(settings, "stats_max_pages", 1)
    p = BallDontLieStatsProvider(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"data": [], "meta": {"next_cursor": 8}})
            )
        )
    )
    with pytest.raises(StatsProviderError, match="page budget"):
        p.fetch(date(2026, 10, 6), date(2026, 11, 4), 2026)
    monkeypatch.setattr(settings, "stats_max_pages", 3)
    with pytest.raises(StatsProviderError, match="invalid"):
        p.fetch(date(2026, 10, 6), date(2026, 11, 4), 2026)


def test_spatial_retry_preserves_roles():
    objects = [
        {"id": 0, "role": "target", "box": [10, 10, 20, 20]},
        {"id": 1, "role": "defender", "box": [30, 10, 40, 20]},
    ]
    clip = {
        "width": 100,
        "height": 100,
        "fps": 12,
        "duration": 2,
        "frames": [{"frame": 0}, {"frame": 6}],
    }
    crit = Criticism(
        quality_score=0.4,
        identity_swaps=[],
        missing_tracking=[],
        incorrect_masks=[],
        occlusion_problems=[],
        retry_justified=True,
        refined_prompt="jersey target",
        explanation="offline fixture",
    )
    assert corrected_prompt(clip, objects, crit) is None
    crit = Criticism.model_validate(
        {**crit.model_dump(), "retry_objects": objects, "retry_frame": 6}
    )
    prompt = corrected_prompt(clip, objects, crit)
    assert prompt.startswith("<6f>") and "1<|box" in prompt
    crit.retry_frame = 7
    with pytest.raises(ModelError, match="inspected"):
        corrected_prompt(clip, objects, crit)


def test_unknown_participation_is_not_reported_as_a_played_game(store):
    value = batch(count=3)
    value.games[0].participation = "unknown"
    league, rid = connect_batch(store, value)
    player = enrich_snapshot(league, store, NOW)["roster"][0]
    assert player["recent"]["sample_size"] == 2
    assert player["recent"]["unknown_participation_count"] == 1
    assert player["recent"]["ready"] is False
