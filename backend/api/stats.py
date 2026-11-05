"""Local read-only league setup and explicit statistics refresh/import controls."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import League, StatsRefresh, PlayerIdentity
from backend.providers.stats_base import StatsBatch
from backend.providers.stats_registry import configured
from backend.services.player_identity import save_identity
from backend.services.stat_enrichment import fingerprint
from backend.services.state import get_league
from backend.worker.stats import enqueue_refresh

router = APIRouter(prefix="/api")


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ref: str = Field(min_length=10, max_length=1000)


class RulesReview(Review):
    game_mode: Literal["lock_in", "game_pick", "unknown"]
    waiver_mode: Literal["faab", "priority", "free_agent", "unknown"]
    point_bonus_mode: Literal["stack", "highest_only", "unknown"]
    faab_budget: int | None = Field(None, ge=0, le=10000)


class MappingReview(Review):
    sleeper_id: str = Field(min_length=1, max_length=100)
    athlete_id: str = Field(min_length=1, max_length=100)


class EligibilityReview(Review):
    player_id: str = Field(min_length=1, max_length=150)
    acquisition: Literal["free_agent", "waivers", "locked", "unknown"]
    drop_allowed: bool


def real_league():
    league = get_league()
    if league.get("is_demo", True):
        raise HTTPException(409, "Use a connected league for statistics and rule reviews.")
    return league


@router.get("/stats")
def stats_status():
    league = real_league()
    with session_scope() as s:
        jobs = s.scalars(
            select(StatsRefresh)
            .where(StatsRefresh.league_id == league["id"])
            .order_by(StatsRefresh.created_at.desc())
            .limit(10)
        ).all()
        links = {
            (m.provider, m.sleeper_id): m
            for m in s.scalars(select(PlayerIdentity))
            if m.data.get("verified")
        }

        def reviews(job):
            provider = job.data.get("provider")
            result = []
            for p in job.data.get("summary", {}).get("identity_review", []):
                link = links.get((provider, p["sleeper_id"]))
                result.append({**p, "status": "verified" if link else p["status"]})
            return result

        return {
            "provider": settings.nba_stats_provider,
            "provider_configured": configured(settings.nba_stats_provider),
            "window_days": settings.stats_window_days,
            "request_limit": settings.stats_max_pages,
            "summary": league.get("stats_summary"),
            "coverage": league.get("stats_coverage"),
            "readiness_reasons": league.get("readiness_reasons", []),
            "jobs": [
                {
                    "id": j.id,
                    "status": j.status,
                    "created_at": j.created_at,
                    "error": j.error,
                    "progress": j.data.get("progress", 0),
                    "identity_review": reviews(j),
                }
                for j in jobs
            ],
        }


@router.post("/stats/refresh", status_code=202)
def refresh_stats():
    try:
        return {"id": enqueue_refresh(real_league())}
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/stats/import", status_code=202)
def import_stats(batch: StatsBatch):
    try:
        return {"id": enqueue_refresh(real_league(), batch)}
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/stats/mappings")
def review_mapping(value: MappingReview):
    league = real_league()
    if value.sleeper_id not in {p["external_id"] for p in league["roster"] + league["available"]}:
        raise HTTPException(422, "Player is not in the current league directory.")
    with session_scope() as s:
        job = s.scalar(
            select(StatsRefresh)
            .where(StatsRefresh.league_id == league["id"], StatsRefresh.status == "COMPLETED")
            .order_by(StatsRefresh.updated_at.desc())
            .limit(1)
        )
        if not job or value.athlete_id not in {a["id"] for a in job.data["summary"]["athletes"]}:
            raise HTTPException(
                422, "Athlete does not exist in the latest complete statistics batch."
            )
        try:
            save_identity(
                s,
                value.sleeper_id,
                job.data["provider"],
                value.athlete_id,
                {
                    "verified": True,
                    "method": "human_review",
                    "source_ref": value.source_ref,
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except ValueError as e:
            raise HTTPException(422, str(e))
    return {"saved": True}


@router.put("/league/rules")
def review_rules(value: RulesReview):
    league = real_league()
    reported_budget = league.get("rule_settings", {}).get("waiver_budget")
    if (
        value.waiver_mode == "faab"
        and value.faab_budget is not None
        and reported_budget is not None
        and value.faab_budget != reported_budget
    ):
        raise HTTPException(
            409,
            "Confirmed FAAB season budget differs from Sleeper. Refresh the connection and check league settings before saving.",
        )
    with session_scope() as s:
        row = s.get(League, league["id"])
        row.data = {
            **row.data,
            "rules": {
                **value.model_dump(),
                "fingerprint": fingerprint(league),
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    return {"saved": True}


@router.put("/league/eligibility")
def review_eligibility(value: EligibilityReview):
    league = real_league()
    if value.player_id not in {p["id"] for p in league["roster"] + league["available"]}:
        raise HTTPException(422, "Player is not in the current league.")
    with session_scope() as s:
        row = s.get(League, league["id"])
        reviews = dict(row.data.get("eligibility_reviews", {}))
        reviews[value.player_id] = {
            **value.model_dump(),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "fingerprint": fingerprint(league),
        }
        row.data = {**row.data, "eligibility_reviews": reviews}
    return {
        "saved": True,
        "notice": "Manual eligibility evidence expires after five minutes. No transaction was executed.",
    }


@router.get("/stats/players/{player_id}")
def player_logs(player_id: str):
    league = real_league()
    player = next((p for p in league["roster"] + league["available"] if p["id"] == player_id), None)
    if not player:
        raise HTTPException(404, "Player not found in current league.")
    return {
        "player": player,
        "recent": player.get("recent"),
        "reported_period_points": player.get("fantasy_points"),
    }
