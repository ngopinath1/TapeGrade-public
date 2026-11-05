"""No fuzzy matching. Unique shared IDs auto-link; name matches require review."""

import re
import unicodedata

from sqlalchemy import select

from backend.db.schema import PlayerIdentity


def normalized_name(name):
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    tokens = re.sub(r"[^a-z0-9 ]", "", text).split()
    while tokens and tokens[-1] in {"jr", "sr", "ii", "iii", "iv"}:
        tokens.pop()
    return " ".join(tokens)


def propose_matches(players, athletes):
    proposals = []
    for p in players:
        shared_fields = ("nba_id", "sportradar_id")
        evidence = [
            (field, a)
            for field in shared_fields
            for a in athletes
            if p.get(field) and getattr(a, field) == str(p[field]).lower()
        ]
        shared = list({a.id: a for _, a in evidence}.values())
        field = evidence[0][0] if evidence else None
        matches = shared or [
            a for a in athletes if normalized_name(a.name) == normalized_name(p["name"])
        ]
        # A shared identifier must be unique on BOTH sides.
        unique_shared = (
            len(shared) == 1
            and sum(str(x.get(field)).lower() == getattr(shared[0], field) for x in players) == 1
        )
        unique_name = (
            len(matches) == 1
            and sum(normalized_name(x["name"]) == normalized_name(p["name"]) for x in players) == 1
        )
        status = (
            "verified"
            if unique_shared
            else "review" if unique_name else "ambiguous" if matches else "unmatched"
        )
        proposals.append(
            {
                "sleeper_id": p["external_id"],
                "player_id": p["id"],
                "name": p["name"],
                "status": status,
                "method": "shared_" + field if unique_shared else "exact_normalized_name",
                "matches": [a.model_dump(mode="json") for a in matches],
            }
        )
    # Cross-player name collisions cannot create multiple bindings to one athlete.
    counts = {}
    for p in proposals:
        if len(p["matches"]) == 1:
            pid = p["matches"][0]["id"]
            counts[pid] = counts.get(pid, 0) + 1
    for p in proposals:
        if len(p["matches"]) == 1 and counts[p["matches"][0]["id"]] > 1:
            p["status"] = "ambiguous"
    return proposals


def save_identity(session, sleeper_id, provider, athlete_id, evidence):
    if not evidence.get("verified") or not evidence.get("source_ref"):
        raise ValueError("Identity mapping requires verification evidence.")
    existing = session.scalar(
        select(PlayerIdentity).where(
            PlayerIdentity.provider == provider, PlayerIdentity.provider_player_id == athlete_id
        )
    )
    reverse = session.scalars(
        select(PlayerIdentity).where(
            PlayerIdentity.provider == provider, PlayerIdentity.sleeper_id == sleeper_id
        )
    ).all()
    if (
        existing
        and existing.sleeper_id != sleeper_id
        or any(r.provider_player_id != athlete_id for r in reverse)
    ):
        raise ValueError("Identity conflict: review existing crosswalk before remapping.")
    if existing:
        existing.data = evidence
    else:
        session.add(
            PlayerIdentity(
                sleeper_id=sleeper_id,
                provider=provider,
                provider_player_id=athlete_id,
                data=evidence,
            )
        )
