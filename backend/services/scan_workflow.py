"""Prepare live scans in the worker; HTTP handlers never fetch film or run models."""

from datetime import date, datetime, timezone

from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import StatsRefresh
from backend.models.base import ModelError
from backend.providers.sleeper import SleeperLeagueProvider, ProviderError
from backend.providers.stats_registry import configured
from backend.services.state import get_league, save_league, get_guardrails
from backend.services.clips import players_with_permitted_clips
from backend.services.scan_readiness import scan_readiness


class PreparationPending(Exception):
    pass


def workflow_status(league):
    real = not league.get("is_demo", True)
    blockers = []
    if not real:
        blockers.append("Connect your Sleeper NBA league to run a live scan.")
    if settings.mock_models:
        blockers.append(
            "This server is running the sample demo. Start TapeGrade in live mode for your league."
        )
    elif not settings.model_api_key.get_secret_value():
        blockers.append("Live analysis needs the model service key configured on this server.")
    if real and not configured(settings.nba_stats_provider):
        blockers.append(
            "Automatic game-log refresh needs a statistics source configured on this server."
        )
    return {
        "automatic": real and not settings.mock_models,
        "can_start": not blockers,
        "blockers": blockers,
        "footage_configured": bool(settings.footage_catalog_path)
        or settings.public_footage_analysis_enabled,
        "public_footage_analysis_enabled": settings.public_footage_analysis_enabled,
        "footage_discovery_enabled": settings.footage_discovery_enabled,
        "stats_updated_at": (league.get("stats_summary") or {}).get("fetched_at"),
        "roster_updated_at": league.get("fetched_at"),
    }


def refresh_roster(league, factory=None):
    connection = league.get("connection") or {}
    if not all(connection.get(k) for k in ("username", "user_id", "league_id")):
        raise ModelError("Reconnect your Sleeper league before scanning.")
    provider = SleeperLeagueProvider()
    try:
        snapshot = provider.snapshot_for(
            {"user_id": connection["user_id"], "username": connection["username"]},
            connection["league_id"],
        )
        if snapshot["id"] != league["id"]:
            raise ModelError("Sleeper returned a different league. Reconnect before scanning.")
        save_league(snapshot, factory, select_workspace=False)
    except ProviderError as error:
        raise ModelError("Could not refresh your Sleeper roster. " + str(error)) from None
    finally:
        provider.client.close()


def statistics_fresh(league):
    summary = league.get("stats_summary") or {}
    try:
        age = (
            datetime.now(timezone.utc) - datetime.fromisoformat(summary["fetched_at"])
        ).total_seconds()
        window_age = (
            datetime.now(timezone.utc).date() - date.fromisoformat(summary["end_date"])
        ).days
        return (
            0 <= window_age <= 1
            and summary.get("complete")
            and not summary.get("synthetic")
            and 0 <= age <= settings.stats_auto_refresh_minutes * 60
            and summary.get("provider") == settings.nba_stats_provider
        )
    except (KeyError, TypeError, ValueError):
        return False


def prepare_live_scan(job):
    if job.cp.get("preparation_done"):
        return
    league = get_league(job.factory, job.league_id)
    if not job.cp.get("roster_refreshed"):
        job.event(
            "SYNCING_LEAGUE",
            "Sleeper",
            "Refreshing your roster, free agents and league settings.",
            2,
        )
        refresh_roster(league, job.factory)
        job.cp["roster_refreshed"] = True
        job.save()
        league = get_league(job.factory, job.league_id)
    if not statistics_fresh(league):
        from backend.worker.stats import enqueue_refresh, run_once

        job.event(
            "UPDATING_STATISTICS",
            "TapeGrade",
            "Updating recent game logs. Your last complete snapshot is preserved until this finishes.",
            4,
        )
        if not job.cp.get("stats_refresh_id"):
            try:
                job.cp["stats_refresh_id"] = enqueue_refresh(league, factory=job.factory)
            except ValueError as error:
                raise ModelError(str(error)) from None
            job.save()
        rid = job.cp["stats_refresh_id"]
        run_once(job.factory, refresh_id=rid)
        with session_scope(job.factory) as session:
            row = session.get(StatsRefresh, rid)
            if row.status in {"RUNNING", "QUEUED"}:
                raise PreparationPending()
            if row.status != "COMPLETED":
                raise ModelError(
                    "Game-log refresh could not finish. " + (row.error or "Try again later.")
                )
        league = get_league(job.factory, job.league_id)
    if not league.get("scouting_ready"):
        job.cp["recovery"] = {
            "destination": "data",
            "section": "rules",
            "label": "Review league data",
        }
        job.save()
        raise ModelError(
            "League refreshed, but a comparison still needs your attention: "
            + league.get(
                "scouting_unavailable_reason", "Review league rules and statistics coverage."
            )
        )
    guards = get_guardrails(job.factory, job.league_id)
    readiness, _ = scan_readiness(league, guards, job.factory)
    filmed = {p["id"] for p in players_with_permitted_clips(league, job.factory)}
    available = [p for p in league["available"] if p.get("recent", {}).get("ready")]
    # Existing permitted footage is useful input, but never substitutes for verification.
    available.sort(
        key=lambda p: (p["id"] not in filmed, -(p.get("recent_fantasy_average") or 0), p["id"])
    )
    available = [{**p, "has_usable_film": p["id"] in filmed} for p in available]
    from backend.agents.scout import explicit_inspection

    requested = explicit_inspection(job.instruction, {**league, "available": available})
    if requested:
        available.sort(key=lambda p: p["id"] not in requested.player_ids)
    from backend.services.observed_players import player_pool

    job.cp["league"] = {
        **league,
        "available": available[:12],
        "scan_readiness": readiness,
        "film_player_pool": player_pool(league),
    }
    job.cp["preparation_done"] = True
    job.cp["recovery"] = None
    job.cp["data_refresh"] = {
        "roster_updated_at": league.get("fetched_at"),
        "stats_updated_at": (league.get("stats_summary") or {}).get("fetched_at"),
        "stats_refresh_id": job.cp.get("stats_refresh_id"),
    }
    job.save()
    job.event(
        "UPDATING_STATISTICS",
        "TapeGrade",
        f"League data ready. Comparing {len(available)} players with supported recent scores.",
        6,
    )
