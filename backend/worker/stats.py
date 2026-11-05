"""Durable bounded refresh jobs, independent of frozen scouting checkpoints."""

from datetime import datetime, timedelta, timezone
import time
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import League, StatsRefresh, now
from backend.providers.stats_base import StatsBatch
from backend.providers.stats_balldontlie import StatsProviderError
from backend.providers.stats_registry import build_provider, configured
from backend.services.stat_enrichment import persist_batch


def enqueue_refresh(league, batch=None, factory=None):
    if league.get("is_demo", True):
        raise ValueError("Statistics refresh belongs to a connected real league.")
    if batch is None and settings.nba_stats_provider not in {"balldontlie", "sportradar"}:
        raise ValueError(
            "Choose a configured statistics provider or import a licensed normalized JSON batch."
        )
    if batch is None and not configured(settings.nba_stats_provider):
        raise ValueError(
            settings.nba_stats_provider.upper()
            + "_API_KEY is not configured locally. No request was made."
        )
    with session_scope(factory) as s:
        active = s.scalar(
            select(StatsRefresh).where(
                StatsRefresh.league_id == league["id"],
                StatsRefresh.status.in_(["QUEUED", "RUNNING"]),
            )
        )
        if active:
            return active.id
        row = StatsRefresh(
            league_id=league["id"],
            data={
                "batch": batch.model_dump(mode="json") if batch else None,
                "provider": batch.provider if batch else settings.nba_stats_provider,
                "window_days": settings.stats_window_days,
                "request_limit": settings.stats_max_pages,
                "timeout_seconds": settings.stats_timeout_seconds,
                "access_level": settings.sportradar_access_level,
                "request_interval": settings.sportradar_min_interval_seconds,
            },
        )
        s.add(row)
        s.flush()
        return row.id


def run_once(factory=None, provider=None, refresh_id=None):
    with session_scope(factory) as s:
        row = s.scalar(
            select(StatsRefresh)
            .where(
                StatsRefresh.status == "QUEUED",
                *([StatsRefresh.id == refresh_id] if refresh_id else []),
            )
            .order_by(StatsRefresh.created_at)
            .limit(1)
        )
        if not row:
            # Interrupted network work is not silently re-issued against a paid source.
            for expired in s.scalars(
                select(StatsRefresh).where(
                    StatsRefresh.status == "RUNNING", StatsRefresh.lease_until < time.time()
                )
            ):
                expired.status, expired.error = (
                    "FAILED",
                    "Interrupted refresh; explicitly refresh again. Last complete snapshot retained.",
                )
            return False
        changed = s.execute(
            update(StatsRefresh)
            .where(StatsRefresh.id == row.id, StatsRefresh.status == "QUEUED")
            .values(
                status="RUNNING",
                lease_until=time.time()
                + row.data.get("timeout_seconds", settings.stats_timeout_seconds)
                + 30,
                updated_at=now(),
            )
        )
        if not changed.rowcount:
            return False
        rid, data = row.id, row.data
        league = s.get(League, row.league_id).data
    source_provider = provider
    try:
        if data.get("batch"):
            batch = StatsBatch.model_validate(data["batch"])
        else:
            end = datetime.now(ZoneInfo("America/New_York")).date()
            start = end - timedelta(days=data.get("window_days", settings.stats_window_days) - 1)
            # Re-fetch the bounded window so final-score corrections and late DNPs replace rows.
            source_provider = source_provider or build_provider(
                data["provider"],
                access_level=data.get("access_level"),
                request_limit=data.get("request_limit"),
                timeout_seconds=data.get("timeout_seconds"),
                request_interval=data.get("request_interval"),
            )
            batch = source_provider.fetch(start, end, int(league["season"]))
            if batch.provider != data["provider"]:
                raise StatsProviderError(
                    "Statistics provider changed unexpectedly; last snapshot retained."
                )
        with session_scope(factory) as s:
            summary = persist_batch(s, batch, league)
            row = s.get(StatsRefresh, rid)
            row.status, row.updated_at, row.lease_until = "COMPLETED", now(), 0
            row.data = {
                "provider": batch.provider,
                "summary": summary,
                "progress": 100,
                "source_audit": getattr(source_provider, "request_audit", []),
            }
    except Exception as e:
        with session_scope(factory) as s:
            row = s.get(StatsRefresh, rid)
            row.status, row.updated_at, row.lease_until = "FAILED", now(), 0
            row.error = (
                str(e)
                if isinstance(e, StatsProviderError)
                else "Invalid or incomplete statistics refresh. Last complete snapshot retained."
            )
            row.data = {
                **row.data,
                "source_audit": getattr(source_provider, "request_audit", []),
                "request_count": getattr(source_provider, "calls", 0),
                "cache_hits": getattr(source_provider, "hits", 0),
            }
    return True
