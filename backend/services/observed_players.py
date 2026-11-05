"""Join visible jerseys to dated rosters, provider IDs and player-owned evidence.

This service uses the scan's existing statistics batch and tracking output. It
does not fetch sources or call a model, and never writes a guessed crosswalk.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from statistics import mean

from sqlalchemy import select

from backend.api.types import Tracking
from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import GameLog, StatsRefresh
from backend.providers.base import ScoringEngine
from backend.providers.stats_base import GameRecord
from backend.services.clip_identity import jersey, team_code
from backend.services.metrics import calculate_metrics
from backend.services.player_identity import normalized_name
from backend.services.stat_enrichment import fingerprint


def player_pool(league):
    fields = (
        "id",
        "external_id",
        "name",
        "team",
        "number",
        "positions",
        "nba_id",
        "sportradar_id",
        "is_demo",
        "injury_status",
    )
    return [
        {**{k: p.get(k) for k in fields}, "availability": availability}
        for field, availability in (
            ("roster", "your_roster"),
            ("available", "available"),
            ("other_rostered", "rostered_elsewhere"),
        )
        for p in league.get(field, [])
    ]


def scoped_tracking(tracking, bindings, object_id):
    """Reassign roles for this player; never reuse another player's metrics."""
    teams = {b["object_id"]: b.get("team") for b in bindings if b.get("team")}
    target_team = teams.get(object_id)
    data = deepcopy(
        tracking
        or {"width": 1, "height": 1, "fps": 1, "prompt": "", "frames": [], "simulated": False}
    )
    for frame in data["frames"]:
        objects = []
        for obj in frame["objects"]:
            role = (
                "ball"
                if obj["role"] == "ball"
                else (
                    "target"
                    if obj["id"] == object_id
                    else (
                        "defender"
                        if target_team and teams.get(obj["id"]) and teams[obj["id"]] != target_team
                        else None
                    )
                )
            )
            if role:
                objects.append({**obj, "role": role})
        frame["objects"] = objects
    return Tracking.model_validate(data)


def summarize_games(observations, batch, league, clock):
    fetched = datetime.fromisoformat(batch["fetched_at"])
    fresh = (
        0 <= (clock - fetched).total_seconds() <= settings.stats_fresh_hours * 3600
        and 0 <= (clock.date() - datetime.fromisoformat(batch["end_date"]).date()).days <= 1
    )
    finals = sorted(
        [
            (rid, g)
            for rid, g in observations
            if g.status == "final" and g.participation == "played"
        ],
        key=lambda x: (x[1].game_date, x[1].game_id),
    )[-5:]
    details, issues = [], []
    for rid, game in finals:
        scored = ScoringEngine().evaluate(
            game.stats.model_dump(), league["scoring"]["weights"], league.get("rules", {})
        )
        issues.extend(scored["reasons"])
        if game.minutes is None or game.minutes <= 0 or game.synthetic:
            issues.append("A game has missing participation data or synthetic statistics.")
        if not 0 <= (clock - game.fetched_at).total_seconds() <= settings.stats_fresh_hours * 3600:
            issues.append("A player observation is stale or future-dated.")
        details.append(
            {
                "row_id": rid,
                "game_id": game.game_id,
                "date": str(game.game_date),
                "minutes": game.minutes,
                "score": scored["score"],
                "stats": game.stats.model_dump(exclude_none=True),
                "source_ref": game.source_ref,
                "coverage": game.coverage,
                "quality_notes": game.quality_notes,
            }
        )
    if len(finals) < 3:
        issues.append("At least three completed observed games are needed for a recommendation.")
    if not fresh or batch.get("synthetic") or not batch.get("complete"):
        issues.append("A current complete, non-synthetic statistics batch is required.")
    if league.get("rules", {}).get("fingerprint") != fingerprint(league):
        issues.append("Scoring settings need confirmation.")
    scores = [g["score"] for g in details if g["score"] is not None]
    average = round(mean(scores), 2) if scores and len(scores) == len(details) else None
    if average is None:
        issues.append("Exact fantasy scores are unavailable for this sample.")
    averages = {}
    for key in ("pts", "reb", "ast", "stl", "blk", "to", "tpm"):
        values = [g["stats"][key] for g in details if key in g["stats"]]
        averages[key] = {
            "value": round(mean(values), 2) if values else None,
            "sample_size": len(values),
        }
    minutes = [g["minutes"] for g in details if g["minutes"] is not None]
    return {
        "ready": not issues,
        "fresh": fresh,
        "synthetic": batch.get("synthetic", True),
        "provider": batch["provider"],
        "fetched_at": batch["fetched_at"],
        "window_start": batch["start_date"],
        "window_end": batch["end_date"],
        "sample_size": len(finals),
        "fantasy_per_game": average,
        "minutes_per_game": round(mean(minutes), 1) if minutes else None,
        "averages": averages,
        "games": details,
        "reasons": sorted(set(issues)),
        "scoring_fingerprint": fingerprint(league),
    }


def performance_review(profile, league):
    stats, film = profile.get("statistics"), profile["film"]
    if not stats or not stats["ready"]:
        return {
            "verdict": "MORE_DATA",
            "source": "evidence_gate",
            "rationale": "More verified recent games are needed before comparing this player with your roster.",
        }
    if profile["availability"] == "rostered_elsewhere":
        return {
            "verdict": "TRADE_RESEARCH",
            "source": "evidence_gate",
            "rationale": "This player is rostered by another team. Use this performance report for trade research; they are not a free-agent add.",
        }
    if profile["availability"] == "unknown":
        return {
            "verdict": "MORE_DATA",
            "source": "evidence_gate",
            "rationale": "Statistics are linked, but this player's membership in your league is not established.",
        }
    if not film["accepted"] or not any(m["value"] is not None for m in film["metrics"]):
        return {
            "verdict": "MONITOR",
            "source": "evidence_gate",
            "rationale": f"Recent production is {stats['fantasy_per_game']:g} fantasy points per game over {stats['sample_size']} games. This player's film tracking needs review before supporting an add.",
        }
    return {
        "verdict": "READY_FOR_REVIEW",
        "source": "evidence_gate",
        "rationale": "Sourced recent production and this player's film measurements are available for the final roster comparison. Availability, scoring and drop rules still apply.",
    }


def build_player_profiles(candidate, league, factory=None, clock=None):
    identity, clip = candidate.get("identity") or {}, candidate.get("clip") or {}
    if identity.get("status") not in {"corroborated", "tracking_rejected"}:
        return []
    context = clip.get("source_identity") or {}
    bindings = identity.get("tracked_players", [])
    pool = league.get("film_player_pool") or player_pool(league)
    refresh_id = candidate["player"].get("recent", {}).get("refresh_id")
    if not refresh_id:
        refresh_id = (league.get("stats_summary") or {}).get("refresh_id")
    batch, logs = None, []
    with session_scope(factory) as s:
        refresh = s.get(StatsRefresh, refresh_id) if refresh_id else None
        if refresh and refresh.league_id == league["id"] and refresh.status == "COMPLETED":
            batch = refresh.data.get("summary")
            if batch:
                logs = [
                    (
                        r.id,
                        GameRecord.model_validate(
                            {k: v for k, v in r.data.items() if k != "coverage"}
                        ),
                    )
                    for r in s.scalars(select(GameLog).where(GameLog.id.in_(batch["game_row_ids"])))
                ]
    clock = clock or datetime.now(timezone.utc)
    if batch:
        logs = [
            (rid, g)
            for rid, g in logs
            if g.provider == batch["provider"]
            and g.season == int(league["season"])
            and g.season_type == "regular"
            and batch["start_date"] <= str(g.game_date) <= batch["end_date"]
            and g.fetched_at <= datetime.fromisoformat(batch["fetched_at"])
        ]
    counts = Counter(b["object_id"] for b in bindings)
    critique = (candidate.get("critiques") or [{}])[-1]
    review = candidate.get("tracking_review")
    continuity_by_id = {}
    for binding in bindings:
        checks = [
            c
            for c in critique.get("player_identity_checks", [])
            if c["object_id"] == binding["object_id"]
        ]
        continuity_by_id[binding["object_id"]] = (
            len(checks) == 1 and checks[0]["identity_preserved"] is True
            if checks
            else binding["role"] == "target" and critique.get("target_identity_preserved") is True
        )
        if review is not None:
            continuity_by_id[binding["object_id"]] = (
                binding["object_id"] in review["trusted_object_ids"]
            )
    trusted_bindings = [
        b for b in bindings if counts[b["object_id"]] == 1 and continuity_by_id[b["object_id"]]
    ]
    profiles = []
    for binding in bindings:
        if (
            binding.get("role") == "ball"
            or not binding.get("name")
            or counts[binding["object_id"]] != 1
        ):
            continue
        matches = [
            p
            for p in context.get("roster", [])
            if normalized_name(p["name"]) == normalized_name(binding["name"])
            and team_code(p["team"]) == team_code(binding.get("team"))
            and jersey(p["jersey_number"]) == jersey(binding.get("jersey_number"))
        ]
        if len(matches) != 1:
            continue
        roster_player = matches[0]
        oid = binding["object_id"]
        continuity = continuity_by_id[oid]
        quality = (
            candidate.get("quality", 0)
            if continuity
            and critique.get("team_roles_preserved") is True
            and not critique.get("role_conflicts")
            and not critique.get("identity_swaps")
            and identity.get("status") == "corroborated"
            else 0
        )
        if review is not None:
            quality = (
                review["quality_by_id"].get(str(oid), 0)
                if continuity and identity.get("status") == "corroborated"
                else 0
            )
        metrics = [
            m.model_dump()
            for m in calculate_metrics(
                scoped_tracking(
                    candidate.get("reviewed_tracking") or candidate.get("tracking"),
                    trusted_bindings,
                    oid,
                ),
                quality if quality >= settings.perception_quality_threshold else 0,
            )
        ]
        profile = {
            "id": "espn:" + roster_player["espn_id"],
            "object_id": oid,
            "name": roster_player["name"],
            "team": roster_player["team"],
            "jersey_number": roster_player["jersey_number"],
            "espn_id": roster_player["espn_id"],
            "nba_id": None,
            "stats_player_id": None,
            "league_player_id": None,
            "availability": "unknown",
            "roster_source": context.get("source_ref"),
            "game_date": clip.get("game_date"),
            "source_clip_id": clip.get("id"),
            "match_status": "stats_unmatched",
            "match_method": None,
            "statistics": None,
            "film": {
                "quality": quality,
                "trusted_object_ids": [b["object_id"] for b in trusted_bindings],
                "accepted": continuity and quality >= settings.perception_quality_threshold,
                "identity_continuity_confirmed": continuity,
                "metrics": metrics,
                "source_ref": clip.get("source_ref"),
                "notice": (
                    "Only this player's track is used; same-team players are excluded from opponent distances."
                    if continuity
                    else "The named seed player has not passed an individual tracking continuity check. Film measurements are withheld."
                ),
            },
        }
        athletes = [
            a
            for a in (batch or {}).get("athletes", [])
            if normalized_name(a["name"]) == normalized_name(roster_player["name"])
            and team_code(a.get("team")) == team_code(roster_player["team"])
            and jersey(a.get("jersey")) == jersey(roster_player["jersey_number"])
        ]
        if len(athletes) == 1:
            athlete = athletes[0]
            games = [(rid, g) for rid, g in logs if g.athlete_id == athlete["id"]]
            if any(
                str(g.game_date) == clip.get("game_date")
                and g.status == "final"
                and g.participation == "played"
                for _, g in games
            ):
                profile.update(
                    match_status="matched",
                    match_method="unique_name_team_jersey_and_dated_game",
                    stats_player_id=athlete["id"],
                    nba_id=athlete.get("nba_id"),
                    statistics=summarize_games(games, batch, league, clock),
                )
                profile["statistics"]["refresh_id"] = refresh_id
                linked = []
                for p in pool:
                    shared = [
                        str(p[k]).lower() == str(athlete[k]).lower()
                        for k in ("nba_id", "sportradar_id")
                        if p.get(k) and athlete.get(k)
                    ]
                    if shared and all(shared):
                        linked.append(p)
                if (
                    len(linked) == 1
                    and normalized_name(linked[0]["name"]) == normalized_name(athlete["name"])
                    and team_code(linked[0].get("team")) == team_code(athlete.get("team"))
                ):
                    profile.update(
                        league_player_id=linked[0]["id"], availability=linked[0]["availability"]
                    )
        profile["recommendation"] = performance_review(profile, league)
        profiles.append(profile)
    return profiles


def add_observed_candidates(candidates, league, guardrails):
    """Reuse accepted tracks for other available players in the SAME decision call."""
    from backend.services.staging import eligible_drops

    pool = league.get("film_player_pool") or player_pool(league)
    known = {c["player"]["id"] for c in candidates}
    extras = []
    for original in candidates:
        for profile in original.get("identified_players", []):
            pid, stats = profile.get("league_player_id"), profile.get("statistics")
            if (
                len(candidates) + len(extras) >= 6
                or pid in known
                or not pid
                or profile["availability"] != "available"
                or not stats
                or not stats["ready"]
                or not profile["film"]["accepted"]
                or not any(
                    m["value"] is not None and m["evidence_frames"]
                    for m in profile["film"]["metrics"]
                )
            ):
                continue
            player = next((p for p in pool if p["id"] == pid), None)
            if not player:
                continue
            player = {
                **player,
                "fantasy_points": None,
                "minutes": stats["minutes_per_game"],
                "previous_minutes": None,
                "stats": {},
                "recent_fantasy_average": stats["fantasy_per_game"],
                "trend": [g["score"] for g in stats["games"]],
                "lineup_status": "Unrostered",
                "recent": {
                    **stats,
                    "identity_id": None,
                    "provider_player_id": profile["stats_player_id"],
                },
            }
            league["available"] = [p for p in league["available"] if p["id"] != pid] + [player]
            player["eligible_drop_ids"], player["transaction_issues"] = eligible_drops(
                league, player, guardrails
            )
            scoped = scoped_tracking(
                original.get("reviewed_tracking") or original["tracking"],
                original["identity"]["tracked_players"],
                profile["object_id"],
            )
            related = {
                **original,
                "player": player,
                "verified": True,
                "quality": profile["film"]["quality"],
                "tracking_accepted": True,
                "tracking": scoped.model_dump(),
                "metrics": profile["film"]["metrics"],
                "overlays": [],
                "observed_from_player_id": original["player"]["id"],
                "observed_object_id": profile["object_id"],
            }
            related.pop("identity", None)
            if original.get("reviewed_tracking") is not None:
                related["reviewed_tracking"] = scoped.model_dump()
                related["tracking_review"] = {
                    **original["tracking_review"],
                    "scene_only": False,
                    "target_quality": profile["film"]["quality"],
                    "roles": {
                        role: len(
                            {o.id for f in scoped.frames for o in f.objects if o.role == role}
                        )
                        for role in ("target", "defender", "ball", "unknown")
                    },
                }
            related["verification"] = {
                "reason": "Named source-roster player independently checked on this tracking ID.",
                "confidence": profile["film"]["quality"],
            }
            extras.append(related)
            known.add(pid)
    return candidates + extras


def apply_profile_verdicts(candidates):
    verdicts = {c["player"]["id"]: c["verdict"] for c in candidates if c.get("verdict")}
    for candidate in candidates:
        for profile in candidate.get("identified_players", []):
            verdict = verdicts.get(profile.get("league_player_id"))
            if verdict:
                profile["recommendation"] = {**verdict, "source": "model_with_guardrails"}
