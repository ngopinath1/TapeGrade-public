"""Observed NBA compatibility exercised with offline, synthetic HTTP fixtures."""

from copy import deepcopy

import httpx
import pytest

from backend.api import routes
from backend.db.database import session_scope
from backend.db.schema import League, Player, ScanRun, Workspace
from backend.providers.sleeper import ProviderError, SleeperLeagueProvider
from backend.services.state import get_guardrails, get_league
from backend.worker.scan import enqueue, run_once


@pytest.fixture
def sleeper_fixture(store, monkeypatch):
    user = {"user_id": "7", "username": "scout", "display_name": "Scout"}
    league = {
        "league_id": "123",
        "name": "Fixture NBA league",
        "sport": "nba",
        "season": "2026",
        "scoring_settings": {"pts": 0.5, "ast": 1, "bonus_pt_40p": 2},
        "settings": {"leg": 3, "waiver_budget": 100},
    }
    roster = {
        "roster_id": 1,
        "owner_id": "7",
        "players": ["11", "12", "13"],
        "starters": ["11", "12"],
        "reserve": [],
        "co_owners": None,
        "settings": {"wins": 1, "losses": 2, "waiver_budget_used": 5},
    }
    players = {
        str(i): {
            "first_name": "Fixture",
            "last_name": str(i),
            "team": "NYK",
            "position": "PG",
            "fantasy_positions": ["PG"],
            "number": i,
            "active": True,
        }
        for i in range(11, 17)
    }
    data = {
        "/v1/user/scout": user,
        "/v1/league/123": league,
        "/v1/league/123/rosters": [
            roster,
            {"roster_id": 2, "owner_id": "8", "players": ["14"], "reserve": ["15"]},
        ],
        "/v1/league/123/users": [
            {"user_id": "7", "metadata": {"team_name": "Actual fixture roster"}}
        ],
        "/v1/players/nba": players,
        "/v1/league/123/matchups/3": [
            {
                "roster_id": 1,
                "points": 24.5,
                "custom_points": None,
                "players_points": {"11": 24.5, "12": 0},
            }
        ],
    }
    seen = []

    def handler(request):
        seen.append(request.url.path)
        result = data[request.url.path]
        if isinstance(result, int):
            return httpx.Response(result, json={"error": "Fixture unavailable"})
        return httpx.Response(200, json=deepcopy(result))

    transport = httpx.MockTransport(handler)
    provider = SleeperLeagueProvider(httpx.Client(transport=transport))
    monkeypatch.setattr(routes, "sleeper", provider)
    return provider, data, seen, transport


def test_nba_direct_id_maps_true_period_points_and_excludes_all_rostered_players(sleeper_fixture):
    provider, data, seen, _ = sleeper_fixture
    snapshot = provider.connect("scout", league_id="123")["snapshot"]
    assert snapshot["is_demo"] is False and snapshot["period_points"] == 24.5
    assert snapshot["period"] == 3 and snapshot["faab_remaining"] == 95
    assert snapshot["scoring"]["weights"] == data["/v1/league/123"]["scoring_settings"]
    assert [p["fantasy_points"] for p in snapshot["roster"]] == [24.5, 0, None]
    assert all(
        p["minutes"] is None and p["stats"] == {} and p["trend"] == [] for p in snapshot["roster"]
    )
    assert [p["external_id"] for p in snapshot["available"]] == ["16"]
    assert {p["external_id"] for p in snapshot["other_rostered"]} == {"14", "15"}
    assert snapshot["scouting_ready"] is False
    assert "not game averages" in snapshot["notice"]
    assert seen == [
        "/v1/user/scout",
        "/v1/league/123",
        "/v1/league/123/rosters",
        "/v1/league/123/users",
        "/v1/players/nba",
        "/v1/league/123/matchups/3",
    ]


def test_player_directory_cached_across_provider_restarts(sleeper_fixture):
    provider, _, seen, transport = sleeper_fixture
    assert len(provider.players()) == 6
    fresh = SleeperLeagueProvider(httpx.Client(transport=transport))
    assert len(fresh.players()) == 6
    assert seen == ["/v1/players/nba"]


def test_missing_matchup_does_not_invent_zero_scores(sleeper_fixture):
    provider, data, _, _ = sleeper_fixture
    data["/v1/league/123/matchups/3"] = 503
    snapshot = provider.connect("scout", league_id="123")["snapshot"]
    assert snapshot["period_points"] is None and snapshot["points_warning"]
    assert all(p["fantasy_points"] is None for p in snapshot["roster"])


@pytest.mark.parametrize(
    "problem", ["not_owner", "malformed_roster", "malformed_directory", "wrong_league"]
)
def test_invalid_or_unmatched_response_is_rejected(sleeper_fixture, problem):
    provider, data, _, _ = sleeper_fixture
    if problem == "not_owner":
        data["/v1/user/scout"]["user_id"] = "99"
    elif problem == "malformed_roster":
        data["/v1/league/123/rosters"][1]["players"] = "14"
    elif problem == "malformed_directory":
        data["/v1/players/nba"] = []
    else:
        data["/v1/league/123"]["league_id"] = "999"
    with pytest.raises(ProviderError):
        provider.connect("scout", league_id="123")


def test_connection_persists_and_isolates_guardrails_jobs_and_demo_history(
    client, store, sleeper_fixture
):
    sid = enqueue("Find a guard", factory=store)
    demo_guards = client.get("/api/settings").json()
    response = client.post("/api/sleeper/connect", json={"username": "scout", "league_id": "123"})
    assert response.status_code == 200, response.text
    snapshot = response.json()["snapshot"]
    live_id = snapshot["id"]
    boot = client.get("/api/bootstrap").json()
    assert boot["demo_mode"] is False and boot["league"]["name"] == "Fixture NBA league"
    assert client.get("/api/scans").json() == []
    assert get_league(store)["id"] == live_id  # new SQLite session, not a process-local selection
    guard = client.get("/api/settings").json()
    guard["max_faab_bid"] = 0
    guard["protected_players"] = [snapshot["roster"][0]["id"]]
    assert client.put("/api/settings", json=guard).status_code == 200
    assert get_guardrails(store, "demo-nba").model_dump() == demo_guards
    refused = client.post("/api/scans", json={"instruction": "Find a guard"})
    assert refused.status_code == 409 and "Recent per-game" in refused.json()["detail"]
    with session_scope(store) as s:
        assert s.get(Workspace, "local").active_league_id == live_id
        assert s.get(League, live_id).is_demo is False
        assert s.get(Player, snapshot["roster"][0]["id"]).is_demo is False
        assert s.query(ScanRun).count() == 1  # only the earlier demo scan exists
    assert run_once(store)  # queued demo retains its own guardrails after changing workspace
    with session_scope(store) as s:
        run = s.get(ScanRun, sid)
        assert run.stage == "COMPLETED", run.error
        assert run.result["staged_move"]["faab_bid"] == 8
    assert client.post("/api/workspace/demo").status_code == 200
    assert client.get("/api/bootstrap").json()["demo_mode"] is True
    assert client.get("/api/settings").json() == demo_guards
    assert client.get("/api/scans").json()[0]["id"] == sid
    assert (
        client.post(
            "/api/sleeper/connect", json={"username": "scout", "league_id": "123"}
        ).status_code
        == 200
    )
    assert client.get("/api/settings").json() == guard


def test_team_defense_directory_entries_are_not_free_agent_athletes(sleeper_fixture):
    provider, data, calls, transport = sleeper_fixture
    data["/v1/players/nba"]["TEAM"] = {
        "first_name": "Fixture",
        "last_name": "Team",
        "team": "NYK",
        "position": "DEF",
        "fantasy_positions": ["DEF"],
        "active": True,
    }
    snapshot = provider.connect("scout", league_id="123")["snapshot"]
    assert all(p["external_id"] != "TEAM" for p in snapshot["available"])
