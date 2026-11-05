"""Enrich a completed report from saved evidence, using zero model/network calls.

python -m scripts.enrich_players --scan-id ID [--write]
The original result is backed up in the ignored cache before an explicit write.
"""

import argparse
from copy import deepcopy
import json

from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import JobEvent, ScanRun, now
from backend.services.observed_players import (
    apply_profile_verdicts,
    build_player_profiles,
    player_pool,
)
from backend.services.state import get_league


def enrich_report(scan_id, write=False):
    with session_scope() as s:
        run = s.get(ScanRun, scan_id)
        if not run or run.stage != "COMPLETED" or not run.result:
            raise ValueError("A completed scan with stored evidence is required.")
        before, checkpoint, calls = deepcopy(run.result), deepcopy(run.checkpoint), run.live_calls
        league_id = run.league_id
    current = get_league(league_id=league_id)
    league = checkpoint["league"]
    # Performance stays on the scan's original batch/scoring. Membership is
    # explicitly timestamped and never confers transaction eligibility.
    league["film_player_pool"] = player_pool(current)
    result = deepcopy(before)
    for candidate in result["candidates"]:
        candidate["identified_players"] = build_player_profiles(candidate, league)
    apply_profile_verdicts(result["candidates"])
    result["player_profile_enrichment"] = {
        "version": 1,
        "updated_at": now(),
        "membership_as_of": current.get("fetched_at"),
        "additional_model_calls": 0,
        "decision_recomputed": False,
    }
    if write:
        folder = settings.data_dir / "cache" / "profile-enrichment"
        folder.mkdir(parents=True, exist_ok=True)
        backup = folder / (scan_id + "-original.json")
        if not backup.exists():
            backup.write_text(json.dumps(before, indent=2) + "\n")
        with session_scope() as s:
            run = s.get(ScanRun, scan_id)
            if run.stage != "COMPLETED" or run.live_calls != calls or run.result != before:
                raise ValueError("Report changed during enrichment; nothing was overwritten.")
            run.result = result
            s.add(
                JobEvent(
                    scan_id=scan_id,
                    stage="COMPLETED",
                    actor="TapeGrade",
                    message="Matched identified players to saved game statistics; no additional model calls. The original decision is preserved.",
                    detail=result["player_profile_enrichment"],
                )
            )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = enrich_report(args.scan_id, args.write)
    print(
        json.dumps(
            {
                "saved": args.write,
                "profiles": [
                    {
                        "name": p["name"],
                        "availability": p["availability"],
                        "matched": p["match_status"],
                        "fantasy_per_game": (p["statistics"] or {}).get("fantasy_per_game"),
                        "verdict": p["recommendation"]["verdict"],
                    }
                    for c in result["candidates"]
                    for p in c.get("identified_players", [])
                ],
                "additional_model_calls": 0,
            }
        )
    )
