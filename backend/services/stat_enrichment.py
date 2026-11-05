"""Immutable scan evidence built from separate identity/game tables on every read."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json

from sqlalchemy import select

from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import GameLog, PlayerIdentity, StatsRefresh
from backend.providers.base import ScoringEngine
from backend.providers.stats_base import GameRecord, StatsBatch
from backend.services.player_identity import propose_matches, save_identity


def fingerprint(league):
    context = {k: league.get(k) for k in ("scoring", "roster_positions", "season")}
    context["rule_settings"] = {
        k: v
        for k, v in league.get("rule_settings", {}).items()
        if k not in {"leg", "last_scored_leg", "daily_waivers_last_ran"}
    }
    return sha256(
        json.dumps(
            context,
            sort_keys=True,
        ).encode()
    ).hexdigest()


def persist_batch(session, batch: StatsBatch, league):
    if not batch.complete:
        raise ValueError("Incomplete pagination cannot replace the last complete snapshot.")
    proposals = propose_matches(league["roster"] + league["available"], batch.athletes)
    for p in proposals:
        if p["status"] == "verified":
            save_identity(
                session,
                p["sleeper_id"],
                batch.provider,
                p["matches"][0]["id"],
                {"verified": True, "method": p["method"], "source_ref": batch.source_ref},
            )
    keys = []
    for game in batch.games:
        row = session.scalar(
            select(GameLog).where(
                GameLog.provider == game.provider,
                GameLog.game_id == game.game_id,
                GameLog.provider_player_id == game.athlete_id,
            )
        )
        data = game.model_dump(mode="json")
        data["coverage"] = game.coverage
        if row:
            # Late arrivals cannot roll back a newer correction.
            old = datetime.fromisoformat(row.data["fetched_at"])
            if game.fetched_at >= old:
                row.data = data
        else:
            row = GameLog(
                provider=game.provider,
                game_id=game.game_id,
                provider_player_id=game.athlete_id,
                data=data,
            )
            session.add(row)
        session.flush()
        keys.append(row.id)
    return {
        "provider": batch.provider,
        "start_date": str(batch.start_date),
        "end_date": str(batch.end_date),
        "fetched_at": batch.fetched_at.isoformat(),
        "source_ref": batch.source_ref,
        "synthetic": batch.synthetic,
        "complete": batch.complete,
        "request_count": batch.request_count,
        "cache_hits": batch.cache_hits,
        "game_row_ids": sorted(set(keys)),
        "athletes": [a.model_dump(mode="json") for a in batch.athletes],
        "identity_review": proposals,
    }


def enrich_snapshot(snapshot, factory=None, clock=None):
    if snapshot.get("is_demo", True):
        return snapshot
    league = deepcopy(snapshot)
    current = clock or datetime.now(timezone.utc)
    reasons = []
    rules = league.get("rules", {})
    if rules.get("fingerprint") != fingerprint(league):
        rules = {}
    league["rules"] = rules
    if rules.get("game_mode") not in ("lock_in", "game_pick"):
        reasons.append(
            "Confirm basketball game mode in League setup; numeric codes are not verified."
        )
    if rules.get("waiver_mode") not in ("faab", "priority", "free_agent"):
        reasons.append("Confirm waiver mode; a budget alone does not establish FAAB.")
    if any(
        league.get("scoring", {}).get("weights", {}).get(k, 0)
        for k in ("bonus_pt_40p", "bonus_pt_50p")
    ) and rules.get("point_bonus_mode") not in ("stack", "highest_only"):
        reasons.append(
            "Verify 40/50-point bonus stacking against an authoritative rule or a scored game."
        )
    try:
        season = int(league.get("season"))
    except (TypeError, ValueError):
        season = None
        reasons.append("League season is unknown.")
    # Protections are optional user overrides. Statistics drive recommendations
    # for everyone else; an empty list never requires a separate approval.
    league["protection_policy"] = "statistics_with_user_overrides"
    with session_scope(factory) as s:
        latest = s.scalar(
            select(StatsRefresh)
            .where(StatsRefresh.league_id == league["id"], StatsRefresh.status == "COMPLETED")
            .order_by(StatsRefresh.updated_at.desc())
            .limit(1)
        )
        last_attempt = s.scalar(
            select(StatsRefresh)
            .where(StatsRefresh.league_id == league["id"])
            .order_by(StatsRefresh.created_at.desc())
            .limit(1)
        )
        if not latest:
            league.update(
                scouting_ready=False,
                scouting_unavailable_reason=" ".join(
                    ["Recent per-game statistics need a complete verified feed.", *reasons]
                ),
                readiness_reasons=["No recent statistics snapshot.", *reasons],
            )
            if last_attempt:
                league["stats_refresh"] = {
                    "id": last_attempt.id,
                    "status": last_attempt.status,
                    "error": last_attempt.error,
                }
            return league
        batch = latest.data["summary"]
        if settings.nba_stats_provider not in {"none", "import", batch["provider"]}:
            reasons.append("Selected statistics provider changed; refresh before recommendations.")
        fetched = datetime.fromisoformat(batch["fetched_at"])
        age = (current - fetched).total_seconds()
        fresh = 0 <= age <= settings.stats_fresh_hours * 3600
        window_age = (current.date() - datetime.fromisoformat(batch["end_date"]).date()).days
        fresh = fresh and 0 <= window_age <= 1
        if not fresh:
            reasons.append("Statistics snapshot is stale or has a future fetch time.")
        if batch["synthetic"]:
            reasons.append("Synthetic statistics cannot qualify a real league.")
        logs = s.scalars(select(GameLog).where(GameLog.id.in_(batch["game_row_ids"]))).all()
        links = s.scalars(
            select(PlayerIdentity).where(PlayerIdentity.provider == batch["provider"])
        ).all()
        mapping = {m.sleeper_id: m for m in links if m.data.get("verified")}
        by_athlete = {}
        for row in logs:
            data = {k: v for k, v in row.data.items() if k != "coverage"}
            g = GameRecord.model_validate(data)
            if (
                g.season == season
                and g.season_type == "regular"
                and str(g.game_date) >= batch["start_date"]
                and str(g.game_date) <= batch["end_date"]
            ):
                by_athlete.setdefault(g.athlete_id, []).append((row.id, g))
        for p in league["roster"] + league["available"]:
            link = mapping.get(p.get("external_id"))
            observations = sorted(
                by_athlete.get(link.provider_player_id, []) if link else [],
                key=lambda pair: (pair[1].game_date, pair[1].game_id),
            )
            # DNP and unfinished games never become zero-valued games.
            finals = [
                (rid, g)
                for rid, g in observations
                if g.status == "final" and g.participation != "dnp"
            ]
            recent, previous = finals[-5:], finals[-10:-5]
            scores, minutes, details, issues = [], [], [], []
            if not link:
                issues.append("Player identity is not verified.")
            for rid, game in recent:
                evaluated = ScoringEngine().evaluate(
                    game.stats.model_dump(), league["scoring"]["weights"], rules
                )
                if evaluated["score"] is None:
                    issues.extend(game.quality_notes)
                game_age = (current - game.fetched_at).total_seconds()
                if game.synthetic or not 0 <= game_age <= settings.stats_fresh_hours * 3600:
                    issues.append("A recent observation is synthetic or stale.")
                if game.participation != "played" or game.minutes is None or game.minutes <= 0:
                    issues.append("A final game's participation/minutes are unknown.")
                if evaluated["score"] is not None and game.participation == "played":
                    scores.append(evaluated["score"])
                issues.extend(evaluated["reasons"])
                if game.minutes is not None and game.participation == "played":
                    minutes.append(game.minutes)
                details.append(
                    {
                        "row_id": rid,
                        "game_id": game.game_id,
                        "date": str(game.game_date),
                        "minutes": game.minutes,
                        "score": evaluated["score"],
                        "stats": game.stats.model_dump(exclude_none=True),
                        "source_ref": game.source_ref,
                        "coverage": game.coverage,
                        "quality_notes": game.quality_notes,
                        "events": evaluated["events"],
                    }
                )
            played_count = sum(g.participation == "played" for _, g in recent)
            if played_count < 3:
                issues.append(
                    "At least three completed observed games are required (maximum five recent games)."
                )
            complete = len(scores) == len(recent) and len(recent) > 0
            ready = complete and not issues and fresh and not batch["synthetic"]
            # Retain an explicitly stale/synthetic displayed average; it never confers readiness.
            avg = round(sum(scores) / len(scores), 2) if complete else None
            prev_minutes = [
                g.minutes
                for _, g in previous
                if g.participation == "played" and g.minutes is not None
            ]
            p.update(
                minutes=round(sum(minutes) / len(minutes), 1) if minutes else None,
                previous_minutes=(
                    round(sum(prev_minutes) / 5, 1) if len(prev_minutes) == 5 else None
                ),
                recent_fantasy_average=avg,
                trend=scores if len(scores) == len(recent) else [],
                recent={
                    "ready": ready,
                    "synthetic": batch["synthetic"],
                    "fresh": fresh,
                    "sample_size": played_count,
                    "recorded_dnp_count": sum(g.participation == "dnp" for _, g in observations),
                    "unknown_participation_count": sum(
                        g.participation == "unknown" for _, g in observations
                    ),
                    "window_start": batch["start_date"],
                    "window_end": batch["end_date"],
                    "provider": batch["provider"],
                    "refresh_id": latest.id,
                    "fetched_at": batch["fetched_at"],
                    "reasons": sorted(set(issues)),
                    "games": details,
                    "identity_id": link.id if link else None,
                    "scoring_fingerprint": fingerprint(league),
                },
            )
        protected = (league.get("guardrails") or {}).get("protected_players", [])
        candidate_count = sum(p["recent"]["ready"] for p in league["available"])
        drop_count = sum(
            p["recent"]["ready"] and p["id"] not in protected for p in league["roster"]
        )
        if not candidate_count or not drop_count:
            reasons.append(
                "Need a mapped candidate and unprotected drop with exact, comparable recent scores."
            )
        league.update(
            notice=(
                f"Actual Sleeper roster and reported period totals. Recent per-game summaries: {batch['provider']}, {batch['start_date']} to {batch['end_date']}; up to five observed games per player. Coverage varies; inspect player evidence. "
                + (
                    "Synthetic statistics cannot qualify real recommendations. "
                    if batch["synthetic"]
                    else ""
                )
                + ("Statistics are stale; recommendations are blocked. " if not fresh else "")
                + "Unrostered status does not establish acquisition eligibility. NBA league-ID compatibility is observed."
            ),
            stats_summary={
                k: v
                for k, v in batch.items()
                if k not in ("athletes", "identity_review", "game_row_ids")
            },
            stats_coverage={"ready_candidates": candidate_count, "ready_drops": drop_count},
            stats_refresh=(
                {"id": last_attempt.id, "status": last_attempt.status, "error": last_attempt.error}
                if last_attempt
                else None
            ),
            scouting_ready=not reasons,
            readiness_reasons=reasons,
            scouting_unavailable_reason=" ".join(reasons),
        )
    return league
