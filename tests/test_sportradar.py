"""Synthetic HTTP contracts; no trial credentials or external requests are used."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json

import httpx
from pydantic import SecretStr
import pytest
from sqlalchemy import select

from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import StatsRefresh
from backend.providers.stats_balldontlie import StatsProviderError
from backend.providers.stats_sportradar import SportradarStatsProvider, normalize_summary
from backend.providers.stats_base import Athlete
from backend.providers.base import ScoringEngine
from backend.services.player_identity import propose_matches
from backend.worker import stats as worker
from tests.test_statistics import sample_league, batch, connect_batch
from backend.services.state import save_league

G1 = "00000000-0000-4000-8000-000000000001"
G2 = "00000000-0000-4000-8000-000000000002"
P1 = "10000000-0000-4000-8000-000000000001"
P2 = "10000000-0000-4000-8000-000000000002"
START, END = date(2026, 10, 29), date(2026, 11, 4)


def summary(gid=G1):
    counts = {
        "minutes": "30:30",
        "points": 20,
        "rebounds": 10,
        "assists": 10,
        "steals": 1,
        "blocks": 0,
        "turnovers": 2,
        "three_points_made": 2,
        "three_points_att": 5,
        "field_goals_made": 6,
        "field_goals_att": 12,
        "free_throws_made": 6,
        "free_throws_att": 6,
        "offensive_rebounds": 2,
        "defensive_rebounds": 8,
        "personal_fouls": 4,
        "tech_fouls": 0,
        "tech_fouls_non_unsportsmanlike": 0,
        "flagrant_fouls": 0,
    }
    return {
        "id": gid,
        "status": "closed",
        "season": {"year": 2026, "type": "REG"},
        "scheduled": "2026-11-02T01:00:00Z",
        "home": {
            "alias": "NYK",
            "players": [
                {
                    "id": P1,
                    "reference": "123",
                    "full_name": "Fixture Roster",
                    "jersey_number": "4",
                    "played": True,
                    "statistics": counts,
                }
            ],
        },
        "away": {
            "alias": "BOS",
            "players": [
                {
                    "id": P2,
                    "full_name": "Fixture Candidate",
                    "played": False,
                    "statistics": {"minutes": "0:00"},
                }
            ],
        },
    }


def schedule():
    return {
        "season": {"year": 2026, "type": "REG"},
        "games": [
            {"id": G1, "status": "closed", "scheduled": "2026-11-02T01:00:00Z"},
            {"id": G2, "status": "closed", "scheduled": "2026-11-03T01:00:00Z"},
            {"id": "not-fetched", "status": "scheduled", "scheduled": "2026-11-04T23:00:00Z"},
            {"id": "not-final", "status": "complete", "scheduled": "2026-11-03T23:00:00Z"},
        ],
    }


class FakeClock:
    def __init__(self):
        self.now = 0
        self.delays = []

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.delays.append(delay)
        self.now += delay


def provider(monkeypatch, handler, **kwargs):
    monkeypatch.setattr(settings, "sportradar_api_key", SecretStr("offline-test-key"))
    clock = FakeClock()
    return (
        SportradarStatsProvider(
            httpx.Client(transport=httpx.MockTransport(handler)),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            **kwargs,
        ),
        clock,
    )


def test_header_auth_all_closed_games_pacing_and_cache(store, monkeypatch):
    calls = []

    def handler(r):
        calls.append(r)
        assert r.headers["x-api-key"] == "offline-test-key"
        assert "offline-test-key" not in str(r.url) and not r.url.query
        gid = r.url.path.split("/")[-2]
        return httpx.Response(
            200, json=schedule() if r.url.path.endswith("schedule.json") else summary(gid)
        )

    p, clock = provider(monkeypatch, handler)
    b = p.fetch(START, END, 2026)
    assert b.complete and b.provider == "sportradar" and len(b.games) == 4
    assert (
        b.request_count == 3
        and b.cache_hits == 0
        and len(clock.delays) == 2
        and all(d >= 1 for d in clock.delays)
    )
    g = b.games[0]
    assert g.game_date == date(2026, 11, 1) and g.minutes == 30.5
    assert g.stats.tf == 0 and g.stats.ff == 0 and g.stats.pf == 4
    assert b.games[1].participation == "dnp" and b.games[1].stats.pts is None
    b2 = p.fetch(START, END, 2026)
    assert len(calls) == 3 and b2.request_count == 0 and b2.cache_hits == 3
    assert b2.games[0].fetched_at == g.fetched_at
    assert "offline-test-key" not in "\n".join(f.read_text() for f in p.root.rglob("*.json"))


@pytest.mark.parametrize(
    "field", ["tech_fouls", "tech_fouls_non_unsportsmanlike", "flagrant_fouls"]
)
def test_missing_fouls_are_not_personal_or_zero(field):
    raw = summary()
    raw["home"]["players"][0]["statistics"].pop(field)
    _, games = normalize_summary(
        raw, G1, 2026, datetime.now(timezone.utc), "offline:synthetic-fixture"
    )
    assert ScoringEngine().score(games[0].stats.model_dump(), {"tf": -2, "ff": -2}) is None
    assert games[0].stats.pf == 4


def test_non_unsportsmanlike_semantics_fail_closed():
    raw = summary()
    raw["home"]["players"][0]["statistics"]["tech_fouls_non_unsportsmanlike"] = 1
    _, games = normalize_summary(
        raw, G1, 2026, datetime.now(timezone.utc), "offline:synthetic-fixture"
    )
    assert games[0].stats.tf is None and games[0].quality_notes


@pytest.mark.parametrize(
    "status,expected",
    [(401, "access denied"), (403, "access denied"), (429, "rate limit"), (503, "unavailable")],
)
def test_failures_sanitized_and_not_retried(store, monkeypatch, status, expected):
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(status, text="offline-test-key", headers={"Retry-After": "60"})

    p, _ = provider(monkeypatch, handler)
    with pytest.raises(StatsProviderError, match=expected) as error:
        p.fetch(START, END, 2026)
    assert len(calls) == 1 and "offline-test-key" not in str(error.value)
    assert not list(p.root.rglob("*.json"))


def test_request_cap_rejects_incomplete_window_before_summaries(store, monkeypatch):
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(200, json=schedule())

    p, _ = provider(monkeypatch, handler, request_limit=2)
    with pytest.raises(StatsProviderError, match="exceeds"):
        p.fetch(START, END, 2026)
    assert len(calls) == 1


def test_time_budget_cannot_be_slept_past(store, monkeypatch):
    p, _ = provider(monkeypatch, lambda r: httpx.Response(200, json=schedule()), timeout_seconds=1)
    with pytest.raises(StatsProviderError, match="time budget"):
        p.fetch(START, END, 2026)
    assert p.calls == 1


def test_stale_cache_is_revalidated(store, monkeypatch):
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(
            200,
            json=(
                schedule()
                if r.url.path.endswith("schedule.json")
                else summary(r.url.path.split("/")[-2])
            ),
        )

    p, _ = provider(monkeypatch, handler)
    p.store_response(
        "games/2026/REG/schedule.json",
        schedule(),
        datetime.now(timezone.utc) - timedelta(minutes=11),
    )
    b = p.fetch(START, END, 2026)
    assert len(calls) == 3 and b.request_count == 3


@pytest.mark.parametrize("issue", ["season", "duplicate", "unfinished", "bad_points", "empty_team"])
def test_invalid_summary_rejected(issue):
    raw = summary()
    if issue == "season":
        raw["season"]["year"] = 2025
    elif issue == "duplicate":
        raw["away"]["players"][0]["id"] = P1
    elif issue == "unfinished":
        raw["status"] = "complete"
    elif issue == "bad_points":
        raw["home"]["players"][0]["statistics"]["points"] = -1
    elif issue == "empty_team":
        raw["away"]["players"] = []
    with pytest.raises(ValueError):
        normalize_summary(raw, G1, 2026, datetime.now(timezone.utc), "offline:synthetic-fixture")


def test_shared_sportradar_id_mapping_and_identifier_conflicts():
    p = {
        "id": "sleeper:fixture:1",
        "external_id": "1",
        "name": "Fixture Roster",
        "sportradar_id": P1,
    }
    a = Athlete(id=P1, sportradar_id=P1, name="Fixture Roster")
    result = propose_matches([p], [a])[0]
    assert result["status"] == "verified" and result["method"] == "shared_sportradar_id"
    other = Athlete(id=P2, sportradar_id=P2, nba_id="123", name="Fixture Other")
    p["nba_id"] = "123"
    assert propose_matches([p], [a, other])[0]["status"] == "ambiguous"


def test_worker_uses_queued_provider_and_preserves_synthetic_label(store, monkeypatch):
    league = sample_league()
    save_league(league, store)
    monkeypatch.setattr(settings, "nba_stats_provider", "sportradar")
    monkeypatch.setattr(settings, "sportradar_api_key", SecretStr("offline-test-key"))
    monkeypatch.setattr(settings, "stats_window_days", 7)
    rid = worker.enqueue_refresh(league, factory=store)
    monkeypatch.setattr(settings, "nba_stats_provider", "none")
    seen = []

    class Stub:
        def fetch(self, start, end, season):
            seen.append((start, end, season))
            value = batch()
            value.provider = "sportradar"
            for g in value.games:
                g.provider = "sportradar"
            return value

    def build(name, **kwargs):
        assert name == "sportradar"
        return Stub()

    monkeypatch.setattr(worker, "build_provider", build)
    assert worker.run_once(store)
    assert (seen[0][1] - seen[0][0]).days == 6
    with session_scope(store) as s:
        row = s.get(StatsRefresh, rid)
        assert row.status == "COMPLETED" and row.data["summary"]["synthetic"]


def test_public_status_never_exposes_source_key(client, store, monkeypatch):
    connect_batch(store)
    monkeypatch.setattr(settings, "nba_stats_provider", "sportradar")
    monkeypatch.setattr(settings, "sportradar_api_key", SecretStr("offline-test-key"))
    r = client.get("/api/stats")
    assert r.json()["provider_configured"] and r.json()["provider"] == "sportradar"
    assert (
        "offline-test-key" not in r.text
        and "offline-test-key" not in client.get("/api/bootstrap").text
    )


@pytest.mark.parametrize("reason", ["inactive", "not_playing_reason"])
def test_explicit_not_playing_metadata_is_dnp_without_played_flag(reason):
    raw = summary()
    p = raw["home"]["players"][0]
    p.pop("played")
    if reason == "inactive":
        p["active"] = False
    else:
        p["not_playing_reason"] = "Inactive - Injury/Illness"
    p["statistics"] = {"minutes": "00:00"}
    _, games = normalize_summary(
        raw, G1, 2026, datetime.now(timezone.utc), "offline:synthetic-fixture"
    )
    assert games[0].participation == "dnp" and games[0].stats.pts is None
