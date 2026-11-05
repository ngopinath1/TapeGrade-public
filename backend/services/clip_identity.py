"""Identity corroboration combines dated roster context with visible jersey evidence.

Publisher titles supply a candidate, not proof. SAM IDs supply continuity, not a
person's name. No face matching or hidden jersey-number assumptions are used.
"""

from hashlib import sha256
import json
import re

from PIL import Image, ImageOps

from backend.config import settings
from backend.services.clips import local_path, media_url
from backend.services.player_identity import normalized_name


def team_code(value):
    value = str(value or "").strip().upper()
    return {"NY": "NYK", "GS": "GSW", "NO": "NOP", "SA": "SAS", "UTAH": "UTA"}.get(value, value)


def jersey(value):
    text = str("" if value is None else value).strip().removeprefix("#")
    return text if re.fullmatch(r"\d{1,2}", text) else None


def game_identity_context(summary, event_id, game_date, player):
    roster = {}
    for group in summary.get("boxscore", {}).get("players", []):
        team = team_code(group.get("team", {}).get("abbreviation"))
        for stat in group.get("statistics", []):
            for record in stat.get("athletes", []):
                if record.get("didNotPlay"):
                    continue
                athlete = record.get("athlete", {})
                name = athlete.get("displayName") or athlete.get("fullName")
                number = jersey(athlete.get("jersey"))
                if name and number is not None and athlete.get("id") and team:
                    roster[(team, str(athlete["id"]))] = {
                        "name": name,
                        "espn_id": str(athlete["id"]),
                        "team": team,
                        "jersey_number": number,
                    }
    matches = [
        p
        for p in roster.values()
        if normalized_name(p["name"]) == normalized_name(player["name"])
        and p["team"] == team_code(player.get("team"))
    ]
    expected = matches[0] if len(matches) == 1 else None
    # The same team/number cannot resolve to two people in the game's roster.
    if (
        expected
        and sum(
            p["team"] == expected["team"] and p["jersey_number"] == expected["jersey_number"]
            for p in roster.values()
        )
        != 1
    ):
        expected = None
    return {
        "version": 2,
        "provider": "ESPN",
        "event_id": str(event_id),
        "game_date": game_date,
        "source_ref": "https://www.espn.com/nba/boxscore/_/gameId/" + str(event_id),
        "match_method": "unique_full_name_team_game_roster",
        "roster_match": bool(expected),
        "expected_player": expected,
        "roster": list(roster.values()),
        "notice": "Roster metadata establishes context; visible jersey evidence is still required.",
    }


def valid_box(box, clip):
    return (
        len(box) == 4
        and 0 <= box[0] < box[2] < clip["width"]
        and 0 <= box[1] < box[3] < clip["height"]
    )


def overlap(a, b):
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - area
    return area / union if union else 0


def review_tracking_identity(identity, critique):
    """Update only the tracking gate; an unconfirmed seed cannot be upgraded here."""
    if identity["status"] == "unconfirmed":
        return False
    reason = "The independent tracking review did not confirm target identity and opposing-team role continuity."
    accepted = (
        critique.target_identity_preserved is True
        and critique.team_roles_preserved is True
        and not critique.role_conflicts
        and not getattr(critique, "identity_swaps", [])
    )
    object_checks = [c for c in getattr(critique, "object_tracking_checks", []) if c.object_id == 1]
    if object_checks:
        # Other objects are filtered independently; defender drift does not negate a clear target.
        accepted = (
            len(object_checks) == 1
            and object_checks[0].identity_preserved
            and object_checks[0].role_correct
            and object_checks[0].quality_score >= settings.perception_quality_threshold
            and critique.target_identity_preserved is True
        )
    target_checks = [c for c in getattr(critique, "player_identity_checks", []) if c.object_id == 1]
    if target_checks:
        accepted = (
            accepted and len(target_checks) == 1 and target_checks[0].identity_preserved is True
        )
    identity["reasons"] = [r for r in identity["reasons"] if r != reason]
    identity["status"] = "corroborated" if accepted else "tracking_rejected"
    if not accepted:
        identity["reasons"].append(reason)
    return accepted


def assess_identity(player, clip, verification):
    context = clip.get("source_identity") or {}
    expected = context.get("expected_player") or {}
    reasons = []
    if (
        not context.get("roster_match")
        or normalized_name(expected.get("name", "")) != normalized_name(player["name"])
        or team_code(expected.get("team")) != team_code(player.get("team"))
    ):
        reasons.append(
            "The dated game roster does not uniquely establish this player's team and jersey number."
        )
    targets = [o for o in verification.objects if o.role == "target"]
    target = targets[0] if len(targets) == 1 else None
    if not target or target.id != 1 or not valid_box(target.box, clip):
        reasons.append("Exactly one valid target seed under tracking ID 1 is required.")
    ids = [o.id for o in verification.objects]
    if len(ids) != len(set(ids)) or any(not valid_box(o.box, clip) for o in verification.objects):
        reasons.append("Tracking seeds contain duplicate IDs or boxes outside the source frame.")
    sampled = {f["frame"] for f in clip["frames"]}
    observations = [o.model_dump() for o in verification.identity_observations]
    usable = [o for o in observations if o["frame"] in sampled and valid_box(o["box"], clip)]
    number = jersey(expected.get("jersey_number"))
    target_team = team_code(expected.get("team"))
    if target and target.jersey_readable and jersey(target.jersey_number) != number:
        reasons.append("The target seed jersey conflicts with the dated roster.")
    clear = [o for o in usable if o["legibility"] == "clear"]
    matched = [
        o
        for o in clear
        if jersey(o["jersey_number"]) == number and team_code(o["team_code"]) == target_team
    ]
    if not number or not matched:
        reasons.append(
            "No clear visible jersey reading matches the dated roster's team and number."
        )
    if any(
        jersey(o["jersey_number"]) != number or team_code(o["team_code"]) != target_team
        for o in clear
    ):
        reasons.append(
            "Visible jersey or team evidence conflicts across the target's sampled frames."
        )
    seed_frame = target.frame if target else 0
    bound = [
        o
        for o in matched
        if o["frame"] == seed_frame and target and overlap(o["box"], target.box) >= 0.35
    ]
    if not bound:
        reasons.append(
            "The identified jersey must be bound to the same player box and frame used to seed tracking."
        )
    continuity = set(verification.continuity_frames)
    if seed_frame not in continuity or len(continuity) < 2 or not continuity <= sampled:
        reasons.append(
            "Continuity needs at least two inspected frames, including the tracking seed frame."
        )
    opponents = {p["team"] for p in context.get("roster", []) if p["team"] != target_team}
    players = []
    for obj in verification.objects:
        team = team_code(obj.team_code)
        number_read = jersey(obj.jersey_number)
        if obj.role == "target" and team != target_team:
            reasons.append("Target seed team does not match the expected player.")
        if obj.role == "defender" and team not in opponents:
            reasons.append("A defender seed is a teammate or has an unestablished team.")
        if obj.role == "ball" and obj.id != 15:
            reasons.append("The ball must use its reserved tracking ID 15.")
        if obj.role == "defender" and not 2 <= obj.id < 15:
            reasons.append("Defender IDs must be distinct from target and ball IDs.")
        bindings = (
            [
                p
                for p in context.get("roster", [])
                if p["team"] == team and p["jersey_number"] == number_read
            ]
            if obj.jersey_readable
            else []
        )
        resolved = bindings[0] if len(bindings) == 1 else None
        if obj.role == "target" and not reasons and expected:
            resolved = expected
        players.append(
            {
                "object_id": obj.id,
                "role": obj.role,
                "name": resolved["name"] if resolved else None,
                "espn_id": resolved["espn_id"] if resolved else None,
                "team": team or None,
                "jersey_number": resolved["jersey_number"] if resolved else number_read,
                "status": "roster_and_jersey_match" if resolved else "unidentified",
            }
        )
    if not verification.verified or verification.confidence < 0.75:
        reasons.append(
            "The visual verifier did not accept the identity with sufficient confidence."
        )
    status = "corroborated" if not reasons else "unconfirmed"
    if status != "corroborated":
        for p in players:
            p.update(name=None, espn_id=None, status="unidentified")
    evidence = []
    for observation in matched[:3]:
        source = next(f for f in clip["frames"] if f["frame"] == observation["frame"])
        box = observation["box"]
        digest = sha256(
            json.dumps([clip["content_hash"], observation], sort_keys=True).encode()
        ).hexdigest()
        path = settings.data_dir / "cache" / "identity" / (digest + ".jpg")
        path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(local_path(source["url"])) as image:
            ImageOps.contain(image.crop((box[0], box[1], box[2] + 1, box[3] + 1)), (200, 300)).save(
                path, quality=92
            )
        evidence.append(
            {
                "frame": source["frame"],
                "time": source["time"],
                "jersey_number": observation["jersey_number"],
                "team": observation["team_code"],
                "crop_url": media_url(path),
                "source_url": source["url"],
                "evidence": observation["evidence"],
            }
        )
    return {
        "version": 2,
        "status": status,
        "expected_name": player["name"],
        "expected_team": target_team,
        "expected_jersey": number,
        "source_ref": context.get("source_ref"),
        "source_date": clip.get("game_date"),
        "method": "dated game roster + visible jersey/team + multi-frame continuity + spatial track ID",
        "reasons": list(dict.fromkeys(reasons)),
        "evidence": evidence,
        "tracked_players": players,
        "continuity_frames": sorted(continuity & sampled),
    }
