"""Read-only scan preflight. Unknown transaction state never becomes addability."""

from backend.config import settings
from backend.services.clips import players_with_permitted_clips
from backend.services.staging import eligible_drops


def scan_readiness(league, guardrails, factory=None):
    real = not league.get("is_demo", True)
    blockers = []
    if real and not league.get("scouting_ready", False):
        blockers.append(league["scouting_unavailable_reason"])
    if real and settings.mock_models:
        blockers.append(
            "Real athletes cannot be analyzed with simulated models. Select the sample league for the mock demonstration."
        )
    available = [p for p in league["available"] if not real or p.get("recent", {}).get("ready")]
    if not settings.mock_models:
        available = players_with_permitted_clips({**league, "available": available}, factory)
        if not available:
            blockers.append(
                f"Upload a permitted clip (up to {settings.max_clip_seconds} seconds) for a statistics-ready free agent in Film library before starting a live scan. No API credits were used."
            )
    candidates = []
    for player in available:
        drops, issues = eligible_drops(league, player, guardrails) if real else ([], [])
        candidates.append({**player, "eligible_drop_ids": drops, "transaction_issues": issues})
    pairs = sum(len(p["eligible_drop_ids"]) for p in candidates)
    notice = (
        "Scouting report only: waiver status and drop locks still need review in League setup. The scan can analyze film, but no ADD or add/drop recommendation will be issued without current eligibility evidence."
        if real and candidates and not pairs
        else None
    )
    return {
        "ready": not blockers,
        "blockers": blockers,
        "notice": notice,
        "eligible_pair_count": pairs,
        "candidates": [
            {k: p[k] for k in ("id", "name", "eligible_drop_ids", "transaction_issues")}
            for p in candidates
        ],
    }, candidates
