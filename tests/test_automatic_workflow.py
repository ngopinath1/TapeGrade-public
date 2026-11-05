"""Offline contracts for automatic preparation and source provenance."""

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import ScanRun, StatsRefresh
from backend.models.base import ModelError
from backend.providers.footage import (
    AutomaticClipProvider,
    ESPNFootageDiscovery,
    FootageError,
    public_media_url,
)
from backend.services.scan_workflow import (
    prepare_live_scan,
    workflow_status,
    statistics_fresh,
    PreparationPending,
)
from backend.services.state import save_league, get_league
from backend.worker.scan import enqueue
from tests.test_statistics import sample_league, batch


def live(monkeypatch):
    monkeypatch.setattr(settings, "mock_models", False)
    monkeypatch.setattr(settings, "model_api_key", SecretStr("offline-contract-key"))
    monkeypatch.setattr(settings, "nba_stats_provider", "sportradar")
    monkeypatch.setattr(settings, "sportradar_api_key", SecretStr("offline-statistics-key"))


def test_automatic_start_does_not_require_preloaded_stats_or_film(store, monkeypatch):
    live(monkeypatch)
    league = sample_league()
    save_league(league, store)
    status = workflow_status(get_league(store))
    assert status["can_start"] and status["automatic"]
    sid = enqueue("Find a useful upgrade", factory=store, prepare=True)
    with session_scope(store) as session:
        row = session.get(ScanRun, sid)
        assert row.mode == "live" and row.checkpoint["automatic_preparation"]
        assert row.live_calls == 0 and row.stage == "QUEUED"


def test_missing_live_key_never_enables_automatic_start(store, monkeypatch):
    live(monkeypatch)
    monkeypatch.setattr(settings, "model_api_key", SecretStr(""))
    save_league(sample_league(), store)
    assert not workflow_status(get_league(store))["can_start"]
    with pytest.raises(ModelError, match="model service key"):
        enqueue("Find a guard", factory=store, prepare=True)


def test_background_refresh_does_not_switch_the_selected_workspace(store):
    first = sample_league()
    save_league(first, store)
    second = json.loads(json.dumps(first))
    second["id"] = "sleeper:other"
    for player in second["roster"] + second["available"]:
        player["id"] = player["id"].replace("sleeper:fixture", "sleeper:other")
    save_league(second, store)
    save_league(first, store, select_workspace=False)
    assert get_league(store)["id"] == second["id"]


def test_statistics_freshness_respects_age_source_and_synthetic_labels(monkeypatch):
    live(monkeypatch)
    summary = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "provider": "sportradar",
        "end_date": str(datetime.now(timezone.utc).date()),
        "complete": True,
        "synthetic": False,
    }
    assert statistics_fresh({"stats_summary": summary})
    assert not statistics_fresh({"stats_summary": {**summary, "synthetic": True}})
    assert not statistics_fresh({"stats_summary": {**summary, "provider": "other"}})
    assert not statistics_fresh(
        {
            "stats_summary": {
                **summary,
                "fetched_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            }
        }
    )


class FakeJob:
    def __init__(self, store):
        self.factory, self.league_id, self.cp, self.events = store, "sleeper:fixture", {}, []
        self.instruction = "Find useful players"

    def event(self, *args):
        self.events.append(args)

    def save(self):
        pass


def test_preparation_refreshes_then_freezes_data_without_repeating_work(store, monkeypatch):
    from backend.services import scan_workflow

    live(monkeypatch)
    league = sample_league()
    league.update(
        scouting_ready=True,
        stats_summary={
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "provider": "sportradar",
            "end_date": str(datetime.now(timezone.utc).date()),
            "complete": True,
            "synthetic": False,
        },
    )
    league["available"][0]["recent"] = {"ready": True}
    refreshed = []
    monkeypatch.setattr(scan_workflow, "get_league", lambda *a: league)
    monkeypatch.setattr(scan_workflow, "refresh_roster", lambda *a: refreshed.append(True))
    monkeypatch.setattr(scan_workflow, "get_guardrails", lambda *a: SimpleNamespace())
    monkeypatch.setattr(scan_workflow, "scan_readiness", lambda *a: ({"notice": "Report only"}, []))
    job = FakeJob(store)
    prepare_live_scan(job)
    prepare_live_scan(job)
    assert refreshed == [True]
    assert job.cp["preparation_done"] and job.cp["data_refresh"]["stats_updated_at"]
    assert job.cp["league"]["available"][0]["id"] == league["available"][0]["id"]


def test_failed_stats_refresh_stops_before_model_work(store, monkeypatch):
    from backend.services import scan_workflow
    from backend.worker import stats

    live(monkeypatch)
    league = sample_league()
    save_league(league, store)
    with session_scope(store) as session:
        row = StatsRefresh(
            league_id=league["id"], status="FAILED", error="Source rate limit reached", data={}
        )
        session.add(row)
        session.flush()
        rid = row.id
    monkeypatch.setattr(scan_workflow, "refresh_roster", lambda *a: None)
    monkeypatch.setattr(stats, "enqueue_refresh", lambda *a, **kw: rid)
    monkeypatch.setattr(stats, "run_once", lambda *a, **kw: False)
    job = FakeJob(store)
    with pytest.raises(ModelError, match="rate limit"):
        prepare_live_scan(job)
    assert not job.cp.get("preparation_done")


def test_stats_refresh_targets_the_owned_job(store):
    from backend.worker.stats import enqueue_refresh, run_once

    league = sample_league()
    save_league(league, store)
    first = enqueue_refresh(league, batch(), store)
    with session_scope(store) as session:
        session.get(StatsRefresh, first).status = "FAILED"
    second = enqueue_refresh(league, batch(), store)
    with session_scope(store) as session:
        session.get(StatsRefresh, first).status = "QUEUED"
    assert run_once(store, refresh_id=second)
    with session_scope(store) as session:
        assert session.get(StatsRefresh, first).status == "QUEUED"
        assert session.get(StatsRefresh, second).status == "COMPLETED"


def test_public_video_metadata_produces_exact_name_viewing_links_not_media(store):
    today = datetime.now(timezone.utc).date().isoformat()
    requested = []

    def handler(request):
        requested.append(str(request.url))
        if "/schedule" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "events": [
                        {
                            "id": "12345",
                            "date": today + "T01:00:00Z",
                            "competitions": [{"status": {"type": {"completed": True}}}],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "videos": [
                    {"id": 123, "headline": "Sam Hauser drills a three"},
                    {"id": 124, "headline": "Someone else scores"},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = ESPNFootageDiscovery(client)
    found = source.find({"name": "Sam Hauser", "team": "BOS"})
    assert len(found) == 1 and found[0]["status"] == "viewing_link_only"
    assert found[0]["url"] == "https://www.espn.com/video/clip/_/id/123"
    assert source.find({"name": "Sam Hauser", "team": "BOS"}) == found
    assert len(requested) == 2 and not any(".mp4" in u for u in requested)


def test_metadata_rate_limits_are_not_retried(store):
    calls = []
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: (calls.append(r), httpx.Response(429))[1])
    )
    source = ESPNFootageDiscovery(client, max_requests=1)
    assert source.find({"name": "Test Player", "team": "BOS"}) == []
    assert len(calls) == 1


def catalog(tmp_path, monkeypatch, **overrides):
    path = tmp_path / "catalog.json"
    entry = {
        "nba_id": "123",
        "game_date": str(datetime.now(timezone.utc).date()),
        "title": "Licensed fixture clip",
        "source_ref": "https://example.com/source",
        "rights_reference": "Test-only licensed source fixture",
        "path": "game.mp4",
        **overrides,
    }
    path.write_text(json.dumps([entry]))
    monkeypatch.setattr(settings, "footage_catalog_path", path)
    monkeypatch.setattr(settings, "footage_media_root", tmp_path)
    return entry


def test_catalog_never_matches_a_different_or_stale_athlete(store, tmp_path, monkeypatch):
    catalog(tmp_path, monkeypatch)
    provider = AutomaticClipProvider(store)
    assert provider.find({"id": "c1", "nba_id": "456"}) is None
    catalog(tmp_path, monkeypatch, game_date="2009-01-01")
    assert AutomaticClipProvider(store).find({"id": "c1", "nba_id": "123"}) is None


def test_catalog_paths_cannot_escape_the_authorized_library(store, tmp_path, monkeypatch):
    catalog(tmp_path, monkeypatch, path="../outside.mp4")
    with pytest.raises(FootageError, match="authorized library"):
        AutomaticClipProvider(store).find({"id": "c1", "nba_id": "123"})


def test_unapproved_remote_hosts_are_rejected_before_network(monkeypatch):
    monkeypatch.setattr(settings, "footage_allowed_hosts", [])
    with pytest.raises(FootageError, match="not authorized"):
        public_media_url("https://unapproved.example.com/game.mp4")
    monkeypatch.setattr(settings, "footage_allowed_hosts", ["127.0.0.1"])
    with pytest.raises(FootageError, match="Private network"):
        public_media_url("https://127.0.0.1/game.mp4")


def test_catalog_automatically_extracts_a_matched_clip_with_provenance(
    store, tmp_path, monkeypatch
):
    from backend.services.sample import ensure_sample
    from backend.services.clips import local_path

    source = ensure_sample("c1")
    catalog(tmp_path, monkeypatch, path=source.name, duration_seconds=1)
    monkeypatch.setattr(settings, "footage_media_root", source.parent)
    clip = AutomaticClipProvider(store).find({"id": "c1", "nba_id": "123"})
    assert clip["automatically_matched"] and clip["duration"] <= 1.1
    assert clip["source"] == "Authorized footage library"
    assert clip["identity_status"] == "pending_visual_verification"
    assert clip["rights_reference"] == "Test-only licensed source fixture"
    assert local_path(clip["url"]).is_file()


def test_reimport_reuses_video_without_leaving_an_unused_output(store, tmp_path, monkeypatch):
    from backend.services.sample import ensure_sample
    from backend.services.clips import local_path

    source = ensure_sample("c1")
    catalog(tmp_path, monkeypatch, path=source.name, duration_seconds=1)
    monkeypatch.setattr(settings, "footage_media_root", source.parent)
    provider = AutomaticClipProvider(store)
    entry = provider.entries()[0]
    first = provider.prepare_entry(entry, {"id": "c1", "nba_id": "123"})
    existing_files = set((settings.data_dir / "uploads").iterdir())
    second = provider.prepare_entry(entry, {"id": "c1", "nba_id": "123"})
    assert first["id"] == second["id"]
    assert set((settings.data_dir / "uploads").iterdir()) == existing_files
    assert local_path(first["url"]).is_file() and source.is_file()


def test_public_media_requires_user_enablement(store):
    provider = AutomaticClipProvider(store)
    assert (
        provider.import_public(
            {"id": "c1", "nba_id": "123"},
            [{"publisher": "ESPN", "_media_url": "https://espnmedia-cdn.akamaized.net/test.mp4"}],
        )
        is None
    )


def test_public_metadata_only_exposes_media_for_explicit_import(store):
    today = datetime.now(timezone.utc).date().isoformat()

    def handler(request):
        if "/schedule" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "events": [
                        {
                            "id": "54321",
                            "date": today + "T20:00:00Z",
                            "competitions": [{"status": {"type": {"completed": True}}}],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "videos": [
                    {
                        "id": 543,
                        "headline": "Sam Hauser scores",
                        "source": "espn",
                        "links": {
                            "source": {"href": "https://espnmedia-cdn.akamaized.net/clip.mp4"}
                        },
                    }
                ]
            },
        )

    source = ESPNFootageDiscovery(httpx.Client(transport=httpx.MockTransport(handler)))
    player = {"name": "Sam Hauser", "team": "BOS"}
    assert "_media_url" not in source.find(player)[0]
    assert source.find(player, include_media=True)[0]["_media_url"].endswith("clip.mp4")


def test_public_import_preserves_source_without_claiming_a_license(store, monkeypatch):
    monkeypatch.setattr(settings, "public_footage_analysis_enabled", True)
    provider = AutomaticClipProvider(store)
    calls = []
    monkeypatch.setattr(
        provider,
        "prepare_entry",
        lambda entry, player, public=False: calls.append((entry, public)) or {"id": "fixture"},
    )
    source = {
        "publisher": "ESPN",
        "title": "Sam Hauser scores",
        "game_date": str(datetime.now(timezone.utc).date()),
        "url": "https://www.espn.com/video/clip/_/id/543",
        "_media_url": "https://espnmedia-cdn.akamaized.net/clip.mp4",
    }
    assert provider.import_public({"id": "c1", "nba_id": "123"}, [source]) == {"id": "fixture"}
    assert calls[0][1] and "not a license grant" in calls[0][0].rights_reference


def test_targeted_claim_does_not_take_an_unrelated_scan(store):
    from backend.worker.scan import claim

    first = enqueue("First request", factory=store)
    second = enqueue("Approved request", factory=store)
    selected = claim(store, scan_id=second)
    assert selected[0] == second
    with session_scope(store) as session:
        assert session.get(ScanRun, first).worker_token is None


def test_explicit_player_inspection_does_not_spend_a_scout_call_or_require_an_add():
    from backend.agents.scout import ScoutAgent

    class NoPaidScout:
        def reason(self, *args, **kwargs):
            raise AssertionError("A named inspection must not spend a scouting call")

    league = {"available": [{"id": "real-player", "name": "Sam Hauser"}]}
    selected = ScoutAgent(NoPaidScout()).shortlist(
        "Review Sam Hauser against my roster. Withhold unsupported moves.", league, 1
    )
    assert selected.player_ids == ["real-player"]
    assert "not an add recommendation" in selected.reasoning


def test_explicit_inspection_does_not_bind_negative_or_ambiguous_names():
    from backend.agents.scout import explicit_inspection

    one = {"available": [{"id": "one", "name": "Sam Hauser"}]}
    assert explicit_inspection("Do not review Sam Hauser", one) is None
    assert explicit_inspection("Review everyone except Sam Hauser", one) is None
    two = {"available": one["available"] + [{"id": "two", "name": "Sam Hauser"}]}
    assert explicit_inspection("Review Sam Hauser", two) is None


def test_public_lookup_prefers_dated_sources_over_undated_legacy_uploads(store, monkeypatch):
    from backend.services.clips import LocalClipProvider

    monkeypatch.setattr(settings, "public_footage_analysis_enabled", True)
    monkeypatch.setattr(
        LocalClipProvider, "find", lambda *args: {"id": "undated-legacy", "duration": 4}
    )
    assert AutomaticClipProvider(store).find({"id": "c1", "nba_id": "123"}) is None
