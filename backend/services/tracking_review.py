"""Keep object detection, named identity and opponent roles separate."""

from collections import Counter

from backend.api.types import Tracking
from backend.config import settings
from backend.services.clip_identity import overlap, team_code, valid_box


def tracking_seeds(clip, verification, identity_confirmed):
    sampled = {f["frame"] for f in clip["frames"]}
    context = clip.get("source_identity") or {}
    target_team = team_code((context.get("expected_player") or {}).get("team"))
    if not target_team:
        target_team = next(
            (team_code(o.team_code) for o in verification.objects if o.role == "target"), ""
        )
    opponents = {
        team_code(p["team"])
        for p in context.get("roster", [])
        if team_code(p["team"]) != target_team
    }
    counts = Counter(o.id for o in verification.objects)
    seeds = []
    target = next((o for o in verification.objects if o.role == "target"), None)
    for obj in verification.objects:
        if counts[obj.id] != 1 or obj.frame not in sampled or not valid_box(obj.box, clip):
            continue
        seed = obj.model_dump()
        if obj.role == "ball":
            if obj.id != 15 and clip.get("public_source"):
                continue
        else:
            if obj.id == 15:
                continue
            if not identity_confirmed:
                seed["role"] = "unknown"
            elif obj.role == "defender":
                team = team_code(obj.team_code)
                if (team and team == target_team) or (opponents and team not in opponents):
                    seed["role"] = "unknown"
                if target and obj.frame == target.frame and overlap(obj.box, target.box) > 0.7:
                    continue
        seeds.append(seed)
    return seeds


def reviewed_tracking(
    tracking, seeds, critique, identity_confirmed, confidence, inspected_frames=None
):
    """A drifting defender must not erase an independently confirmed target."""
    checks = critique.object_tracking_checks
    if not checks:
        return None, None
    counts = Counter(c.object_id for c in checks)
    by_id = {c.object_id: c for c in checks if counts[c.object_id] == 1}
    bindings = {o["id"]: o for o in seeds}
    threshold = settings.perception_quality_threshold
    quality, cutoffs, issues = {}, {}, []
    for oid, seed in bindings.items():
        check = by_id.get(oid)
        if not check:
            issues.append(f"Object {oid} was not independently reviewed.")
            continue
        cutoff = check.unreliable_from_frame
        if cutoff is not None and (
            (inspected_frames is not None and cutoff not in inspected_frames)
            or cutoff <= seed.get("frame", 0)
        ):
            issues.append(f"Object {oid}: loss frame was not inspected.")
            continue
        reliable_prefix = cutoff is not None and cutoff > seed.get("frame", 0)
        accepted = (
            check.role_correct
            and (check.identity_preserved or reliable_prefix)
            and check.quality_score >= threshold
        )
        if accepted:
            quality[oid] = (
                min(check.quality_score, confidence)
                if seed["role"] == "target"
                else check.quality_score
            )
            cutoffs[oid] = cutoff
        else:
            issues.append(f"Object {oid}: {check.reason}")
    frames = []
    for frame in tracking.frames:
        objects = []
        for obj in frame.objects:
            seed = bindings.get(obj.id)
            if not seed or obj.id not in quality:
                continue
            cutoff = cutoffs[obj.id]
            if cutoff is not None and frame.frame >= cutoff:
                continue
            role = seed["role"] if identity_confirmed or seed["role"] == "ball" else "unknown"
            objects.append({**obj.model_dump(), "role": role})
        frames.append({"frame": frame.frame, "time": frame.time, "objects": objects})
    reviewed = Tracking.model_validate({**tracking.model_dump(), "frames": frames})
    observed_ids = {o.id for f in reviewed.frames for o in f.objects}
    quality = {oid: q for oid, q in quality.items() if oid in observed_ids}
    target_id = next((o["id"] for o in seeds if o["role"] == "target"), None)
    summary = {
        "scene_only": not identity_confirmed,
        "quality_by_id": {str(oid): q for oid, q in quality.items()},
        "trusted_object_ids": sorted(quality),
        "target_quality": quality.get(target_id, 0) if identity_confirmed else 0,
        "issues": issues,
        "roles": {
            role: len({o.id for f in reviewed.frames for o in f.objects if o.role == role})
            for role in ("target", "defender", "ball", "unknown")
        },
    }
    return reviewed, summary
