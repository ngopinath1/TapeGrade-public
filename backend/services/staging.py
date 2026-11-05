from datetime import datetime, timezone
import math

from backend.api.types import Decision, Guardrails
from backend.services.stat_enrichment import fingerprint


def position_feasible(players, slots):
    """Bipartite slot assignment after a proposed add/drop, including bench capacity."""
    slots = [s for s in slots if s not in {"IR", "IR+", "RES", "TAXI"}]
    players = [p for p in players if p.get("lineup_status") != "Reserve"]
    if not slots or len(players) > len(slots):
        return False
    groups = {"G": {"PG", "SG", "G"}, "F": {"SF", "PF", "F"}}
    matches = {}

    def place(index, seen):
        positions = set(players[index].get("positions", []))
        if not positions:
            return False
        for j, slot in enumerate(slots):
            if j in seen or not (slot in {"BN", "UTIL"} or positions & groups.get(slot, {slot})):
                continue
            seen.add(j)
            if j not in matches or place(matches[j], seen):
                matches[j] = index
                return True
        return False

    return all(place(i, set()) for i in range(len(players)))


def live_move_issues(league, add, drop, roster):
    issues = []
    rules = league.get("rules", {})
    if not league.get("scouting_ready") or rules.get("fingerprint") != fingerprint(league):
        issues.append("Current league/scoring readiness is not verified.")
    if (league.get("rule_settings") or {}).get("disable_adds") != 0:
        issues.append("Adds are disabled or their permission is unknown.")
    if add["id"] not in {p["id"] for p in league["available"]}:
        issues.append("Candidate is no longer unrostered.")
    current_add = next((p for p in league["available"] if p["id"] == add["id"]), {})
    if not current_add.get("recent", {}).get("ready") or current_add.get("recent", {}).get(
        "refresh_id"
    ) != add.get("recent", {}).get("refresh_id"):
        issues.append(
            "Candidate statistics changed or lost coverage during the scan; run a fresh comparison."
        )
    for p in [add, drop]:
        if not p.get("recent", {}).get("ready"):
            issues.append("Exact recent statistics are missing for " + p["name"] + ".")
    a, d = add.get("recent", {}), drop.get("recent", {})
    if any(
        a.get(k) != d.get(k)
        for k in ("provider", "window_start", "window_end", "scoring_fingerprint", "refresh_id")
    ):
        issues.append("Candidate and drop statistics are not comparable.")
    current = datetime.now(timezone.utc)

    def fresh(value):
        try:
            return 0 <= (current - datetime.fromisoformat(value)).total_seconds() <= 300
        except (ValueError, TypeError):
            return False

    if not fresh(league.get("fetched_at")):
        issues.append("Refresh Sleeper membership and rules within five minutes of staging.")
    reviews = league.get("eligibility_reviews", {})
    for p in [add, drop]:
        review = reviews.get(p["id"], {})
        if not fresh(review.get("reviewed_at")) or review.get("fingerprint") != fingerprint(league):
            issues.append("Current availability/lock evidence is unknown for " + p["name"] + ".")
    acquire = reviews.get(add["id"], {}).get("acquisition")
    if acquire not in {"free_agent", "waivers"}:
        issues.append("Acquisition eligibility is unknown or locked.")
    if not reviews.get(drop["id"], {}).get("drop_allowed"):
        issues.append("Drop eligibility/Lock-In status is unknown or locked.")
    if acquire == "waivers" and rules.get("waiver_mode") not in {"faab", "priority"}:
        issues.append("Waiver mode is unverified for this claim.")
    if not position_feasible(
        [p for p in roster if p["id"] != drop["id"]] + [add], league.get("roster_positions", [])
    ):
        issues.append("Roster capacity or position eligibility could not be validated.")
    return issues


def eligible_drops(league, add, guardrails):
    """Transaction evidence is separate from permission to inspect film."""
    options, gaps = [], []
    for drop in league["roster"]:
        if drop["id"] in guardrails.protected_players:
            continue
        issues = live_move_issues(league, add, drop, league["roster"])
        if not issues:
            options.append(drop["id"])
        gaps.append(issues)
    acquisition = league.get("eligibility_reviews", {}).get(add["id"], {}).get("acquisition")
    if (
        acquisition == "waivers"
        and league.get("rules", {}).get("waiver_mode") == "faab"
        and league.get("faab_remaining") is None
    ):
        return [], ["Current remaining FAAB budget is unavailable."]
    if options:
        return options, []
    return [], min(gaps, key=len) if gaps else ["All rostered players are protected."]


def validate_decision(
    decision: Decision,
    candidates: list[dict],
    roster: list[dict],
    guardrails: Guardrails,
    budget: int | float | None,
    league: dict | None = None,
) -> tuple[Decision, dict | None]:
    """Model output is advisory. Deterministic code enforces transaction rules."""
    candidates_by_id = {c["player"]["id"]: c for c in candidates}
    roster_by_id = {p["id"]: p for p in roster}
    seen = set()
    for v in decision.verdicts:
        if v.player_id not in candidates_by_id or v.player_id in seen:
            raise ValueError("Model returned an unknown or duplicate candidate.")
        seen.add(v.player_id)
        c = candidates_by_id[v.player_id]
        measured = {
            m["name"] for m in c["metrics"] if m["value"] is not None and m["evidence_frames"]
        }
        if not set(v.metric_refs).issubset(measured):
            raise ValueError("Verdict references an unavailable or unknown metric.")
        v.confidence = min(v.confidence, c["quality"])
        if v.verdict == "ADD" and (
            not v.metric_refs
            or not c.get("verified")
            or c["quality"] < 0.75
            or v.confidence < guardrails.min_confidence
        ):
            v.verdict = "MONITOR"
            v.weaknesses.append(
                "ADD withheld: verified film evidence or confidence threshold not met."
            )
        if v.verdict == "ADD" and c["player"].get("is_demo") is False:
            drops, issues = (
                eligible_drops({**league, "faab_remaining": budget}, c["player"], guardrails)
                if league
                else ([], ["Live league rules are unavailable."])
            )
            if not drops:
                v.verdict = "MONITOR"
                v.weaknesses.extend(["Add/drop recommendation awaits eligibility review.", *issues])
    if seen != set(candidates_by_id):
        raise ValueError("Decision must cover every shortlisted candidate.")
    move = decision.move
    if move is None:
        return decision, None
    v = next((v for v in decision.verdicts if v.player_id == move.add_player_id), None)
    if (
        v is None
        or v.verdict != "ADD"
        or move.drop_player_id not in roster_by_id
        or move.drop_player_id in guardrails.protected_players
        or move.add_player_id in roster_by_id
    ):
        decision.move = None
        return decision, None
    add, drop = candidates_by_id[move.add_player_id]["player"], roster_by_id[move.drop_player_id]
    is_real = add.get("is_demo") is False
    if is_real:
        issues = (
            live_move_issues(league, add, drop, roster)
            if league
            else ["Live league rules are unavailable."]
        )
        if issues:
            v.verdict = "MONITOR"
            v.weaknesses.extend(issues)
            decision.move = None
            return decision, None
        acquire = league["eligibility_reviews"][add["id"]]["acquisition"]
        faab = acquire == "waivers" and league["rules"]["waiver_mode"] == "faab"
    else:
        faab = True
    if faab:
        if (
            budget is None
            or isinstance(budget, bool)
            or not isinstance(budget, (int, float))
            or not math.isfinite(budget)
            or budget < 0
            or move.faab_bid is None
        ):
            decision.move = None
            return decision, None
        move.faab_bid = min(move.faab_bid, guardrails.max_faab_bid, int(budget))
    else:
        move.faab_bid = None
    staged = {
        **move.model_dump(),
        "add_player": add,
        "drop_player": drop,
        "status": "Awaiting your tap",
        "guardrails_checked": True,
        "executed": False,
        "eligibility_source": (
            "Reviewed current Sleeper state" if is_real else "Fictional sample rules"
        ),
    }
    return decision, staged
