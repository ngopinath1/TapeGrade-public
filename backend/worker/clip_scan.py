"""Budgeted film evaluation and automatic distinct-clip fallback."""

from hashlib import sha256
import json

from sqlalchemy import select

from backend.agents.critic import PerceptionCritic
from backend.api.types import ClipVerification, ClipIdentityChecks, SeedObject, Tracking
from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import PerceptionLog, SegmentationResult
from backend.models.base import ModelError
from backend.providers.footage import FootageError
from backend.services.clips import LocalClipProvider, source_key, overlapping_source
from backend.services.metrics import calculate_metrics
from backend.services.overlays import create_overlays
from backend.services.tracking_review import tracking_seeds, reviewed_tracking


def verification_payload(player, clip):
    return {
        "player": player,
        "clip": clip,
        "instruction": "Inspect ALL supplied frames. Separate named identity verification from visible-object detection. Use each object's clearest inspected frame (set its frame field), not necessarily frame 0. Seed named target id 1 only when supported; choose its clearest jersey frame. Seed up to three visible opposing players id 2-14 only when their team is established relative to the confirmed target; teammates, referees and uncertain teams must never be defenders. If the named target cannot be verified, still return up to four clearly visible players with role=unknown and unique ids 1-14. Look explicitly for the basketball across ALL sampled frames, including in a player's hands and in flight; if visibly present, give it reserved id 15, a tight box and its clearest frame. A hand, shoe, logo or inferred hidden ball is not a basketball. Never invent unseen objects. Keep identity verified=false when uncertain, even if visible unknown players can be seeded.",
        "image_frames": [
            {"image_index": i, "source_frame": f["frame"], "time": f["time"]}
            for i, f in enumerate(clip["frames"])
        ],
        "identity_requirements": (
            "The source roster is context, not visual proof. Read the target's jersey from the actual images: return identity_observations (source frame, jersey_number, team_code, clear/unclear legibility, full-frame source-pixel player box and brief evidence). Include a clear read bound to target ID 1 in its chosen seed frame and continuity_frames for at least two supplied frames. A target absent or unreadable at frame 0 can be verified from a later clear sampled frame plus another continuity frame. Never copy the expected number into an observation when it is not legible. If the number/team is uncertain, set verified=false and return visible people as unknown scene objects instead. For each seed object provide team_code and, only when visibly readable, jersey_number and jersey_readable. Defenders must belong to the opponent; same-team players and referees are not defenders. The ball must have ID 15 and is omitted only when not clearly visible in ANY supplied frame. Return only observed people/objects. Do not infer a player's name from face resemblance."
            if clip.get("public_source")
            else None
        ),
    }


def analyze_clip(
    job,
    spark,
    sam,
    player,
    clip,
    mock,
    footage_sources,
    footage_notice,
    verification=None,
    clip_index=0,
    allow_sam_retries=True,
):
    pid, scan_id, factory = player["id"], job.id, job.factory
    league = job.cp["league"]
    candidate = {
        "player": player,
        "clip": clip,
        "verified": False,
        "quality": 0,
        "tracking_accepted": False,
        "tracking": None,
        "metrics": [],
        "critiques": [],
        "overlays": [],
        "footage_sources": footage_sources,
        "footage_notice": footage_notice,
    }
    if not clip or (verification is None and job.remaining_calls() < 2):
        if clip:
            candidate["footage_notice"] = (
                "The remaining call budget is reserved for the final report; film checks were not started."
            )
        job.event(
            "FINDING_CLIPS",
            "TapeGrade",
            (
                "No permitted clip available; film metrics will be unavailable."
                if not clip
                else "The remaining call budget is reserved for the final report; film checks were not started."
            ),
        )
    else:
        job.event(
            "VERIFYING",
            "Muse Spark",
            f"Checking whether the selected clip features {player['name']}.",
        )
        verification = verification or spark.reason(
            "verify",
            verification_payload(player, clip),
            ClipVerification,
            [f["url"] for f in clip["frames"]],
        )
        candidate["verification"] = verification.model_dump()
        candidate["verified"] = verification.verified and verification.confidence >= 0.75
        objects = (
            [o.model_dump() for o in verification.objects]
            if mock
            else tracking_seeds(clip, verification, candidate["verified"])
        )
        verification = verification.model_copy(
            update={"objects": [SeedObject.model_validate(o) for o in objects]}
        )
        if clip.get("public_source"):
            from backend.services.clip_identity import assess_identity

            candidate["identity"] = assess_identity(player, clip, verification)
            candidate["verified"] = (
                candidate["verified"] and candidate["identity"]["status"] == "corroborated"
            )
        if not mock and not candidate["verified"]:
            objects = tracking_seeds(clip, verification, False)
        can_track = candidate["verified"] or (
            not mock and any(o["role"] == "unknown" for o in objects)
        )
        if not candidate["verified"]:
            reason = (
                "; ".join(candidate.get("identity", {}).get("reasons", [])) or verification.reason
            )
            job.event(
                "VERIFYING",
                "Muse Spark",
                f"Named identity unconfirmed: {reason}"
                + (
                    " Tracking visible people without assigning a name or opponent role."
                    if can_track
                    else ""
                ),
            )
        if can_track and job.remaining_calls() < 3:
            candidate["footage_notice"] = (
                "The remaining call budget is reserved for the final report; tracking this clip was not started."
            )
            job.event("VERIFYING", "TapeGrade", candidate["footage_notice"])
        elif can_track:
            prompt = verification.target_description
            if (
                not mock
                and candidate["verified"]
                and not any(o["role"] == "target" for o in objects)
            ):
                raise ModelError("Verified clip has no target seed box. Add clearer footage.")
            if not mock:
                from backend.models.sam import seed_prompt

                prompt = seed_prompt(clip, objects, require_target=candidate["verified"])
            for attempt in range(job.cp["max_sam_retries"] + 1 if allow_sam_retries else 1):
                record_attempt = clip_index * (job.cp["max_sam_retries"] + 1) + attempt
                job.event(
                    "TRACKING",
                    "SAM 3.1",
                    f"{'Retrying tracking' if attempt else 'Tracking clip'} · {player['name']} · attempt {attempt+1}.",
                    detail={"prompt": prompt, "attempt": attempt, "simulated": mock},
                )
                track_payload = {
                    "clip_hash": clip["content_hash"],
                    "prompt": prompt,
                    "objects": objects,
                    "mask_encoding": "one_bit",
                    "tracking_review_version": 3,
                }
                track_data = job.cached(
                    settings.sam_model,
                    "tracking",
                    track_payload,
                    lambda: sam.track(clip, prompt, objects).model_dump(),
                )
                tracking = Tracking.model_validate(track_data)
                seg_key = sha256(
                    json.dumps(
                        {"mode": job.mode, "model": settings.sam_model, **track_payload},
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                with session_scope(factory) as s:
                    if not s.scalar(
                        select(SegmentationResult).where(SegmentationResult.cache_key == seg_key)
                    ):
                        s.add(
                            SegmentationResult(
                                cache_key=seg_key,
                                clip_id=clip["id"],
                                model=settings.sam_model,
                                mode=job.mode,
                                data=track_data,
                            )
                        )
                overlays = create_overlays(clip, tracking, seg_key)
                job.event(
                    "CRITIQUING",
                    "Muse Spark",
                    "Inspecting source frames and tracking overlays for identity swaps and mask errors.",
                )
                # Raw frames plus overlays allow the critic to compare evidence directly.
                critique = PerceptionCritic(spark).inspect(
                    pid,
                    attempt,
                    tracking,
                    [f["url"] for f in clip["frames"]] + overlays,
                    objects,
                    candidate.get("identity"),
                    clip["frames"],
                )
                candidate["critiques"].append(
                    {
                        "attempt": record_attempt,
                        "clip_id": clip["id"],
                        "clip_attempt": clip_index + 1,
                        "tracking_attempt": attempt + 1,
                        "prompt": prompt,
                        **critique.model_dump(),
                    }
                )
                with session_scope(factory) as s:
                    row = s.scalar(
                        select(PerceptionLog).where(
                            PerceptionLog.scan_id == scan_id,
                            PerceptionLog.player_id == pid,
                            PerceptionLog.attempt == record_attempt,
                        )
                    )
                    if row:
                        row.data = candidate["critiques"][-1]
                    else:
                        s.add(
                            PerceptionLog(
                                scan_id=scan_id,
                                player_id=pid,
                                attempt=record_attempt,
                                data=candidate["critiques"][-1],
                            )
                        )
                candidate.update(
                    quality=min(critique.quality_score, verification.confidence),
                    tracking=track_data,
                    overlays=overlays,
                )
                reviewed, summary = reviewed_tracking(
                    tracking,
                    objects,
                    critique,
                    candidate["verified"],
                    verification.confidence,
                    {f["frame"] for f in clip["frames"]},
                )
                if summary is not None:
                    candidate.update(
                        reviewed_tracking=reviewed.model_dump(),
                        tracking_review=summary,
                        quality=summary["target_quality"],
                    )
                if candidate.get("identity"):
                    from backend.services.clip_identity import review_tracking_identity

                    if not review_tracking_identity(candidate["identity"], critique):
                        candidate["quality"] = 0
                        if reviewed is not None:
                            for frame in reviewed.frames:
                                for obj in frame.objects:
                                    if obj.role != "ball":
                                        obj.role = "unknown"
                            summary["scene_only"] = True
                            summary["target_quality"] = 0
                            summary["roles"] = {
                                role: len(
                                    {
                                        o.id
                                        for f in reviewed.frames
                                        for o in f.objects
                                        if o.role == role
                                    }
                                )
                                for role in ("target", "defender", "ball", "unknown")
                            }
                            candidate["reviewed_tracking"] = reviewed.model_dump()
                visible = reviewed or tracking
                accepted = (
                    candidate["verified"]
                    and candidate["quality"] >= settings.perception_quality_threshold
                    and any(o.role == "target" for f in visible.frames for o in f.objects)
                )
                candidate["tracking_accepted"] = accepted
                retry = (
                    (not accepted or bool(summary and summary["issues"]))
                    and critique.retry_justified
                    and attempt < job.cp["max_sam_retries"]
                    and allow_sam_retries
                    and job.remaining_calls() >= 3
                )
                if mock:
                    next_prompt = critique.refined_prompt.strip()
                else:
                    from backend.models.sam import corrected_prompt

                    next_prompt = corrected_prompt(clip, objects, critique) if retry else None
                changed = bool(next_prompt) and next_prompt != prompt
                if retry and changed:
                    job.event(
                        "CRITIQUING",
                        "Muse Spark",
                        f"Tracking quality insufficient ({critique.quality_score:.0%}). {critique.explanation}",
                        detail=critique.model_dump(),
                    )
                    prompt = next_prompt
                    continue
                job.event(
                    "CRITIQUING",
                    "Muse Spark",
                    f"{'Updated tracking accepted' if attempt and accepted else 'Tracking accepted' if accepted else 'Tracking remains unreliable; measurements withheld'} ({candidate['quality']:.0%}).",
                    detail={**critique.model_dump(), "tracking_accepted": accepted},
                )
                break
    job.event(
        "CALCULATING_METRICS",
        "TapeGrade",
        f"Calculating evidence-backed proxies for {player['name']}.",
    )
    tracking = (
        Tracking.model_validate(candidate.get("reviewed_tracking") or candidate["tracking"])
        if candidate["tracking"]
        else Tracking(width=1, height=1, fps=1, prompt="", frames=[], simulated=mock)
    )
    candidate["metrics"] = [
        m.model_dump()
        for m in calculate_metrics(
            tracking, candidate["quality"] if candidate["tracking_accepted"] else 0
        )
    ]
    if candidate.get("identity"):
        from backend.services.observed_players import build_player_profiles

        candidate["identified_players"] = build_player_profiles(candidate, league, factory)
        primary = next((p for p in candidate["identified_players"] if p["object_id"] == 1), None)
        if primary:
            candidate["metrics"] = primary["film"]["metrics"]
            candidate["quality"] = primary["film"]["quality"]
            candidate["tracking_accepted"] = primary["film"]["accepted"]
            if candidate["tracking_accepted"]:
                trusted = set(primary["film"]["trusted_object_ids"])
                for frame in candidate["tracking"]["frames"]:
                    frame["objects"] = [
                        o for o in frame["objects"] if o["id"] in trusted or o["role"] == "ball"
                    ]
    return candidate


def clip_plan(job, player, mock, provider, discovery, progress):
    pid = player["id"]
    plans = job.cp.setdefault("clip_plans", {})
    if pid in plans:
        return plans[pid]
    limit = min(
        settings.max_clips_per_candidate,
        job.cp.get("max_clips_per_candidate", settings.max_clips_per_candidate),
    )
    if mock:
        limit = 1
    job.event(
        "FINDING_CLIPS",
        "TapeGrade",
        f"Finding up to {limit} distinct recent clips for {player['name']}.",
        progress,
    )
    clips, ids, hashes, refs = [], set(), set(), set()
    sources, notice, blocked = None, None, False
    start_requests = discovery.request_count if discovery else 0
    start_hits = discovery.cache_hits if discovery else 0
    for _ in range(limit * 2):
        if len(clips) >= limit:
            break
        clip = None
        try:
            if not job.cp.get("force_footage_discovery"):
                clip = (
                    provider.find(player, ids, hashes, refs)
                    if provider
                    else LocalClipProvider(mock, job.factory).find(pid, ids, hashes, refs)
                )
        except FootageError as error:
            notice = str(error)
        if not clip and provider and not blocked:
            if sources is None:
                sources = (
                    discovery.find(player, include_media=settings.public_footage_analysis_enabled)
                    if discovery
                    else []
                )
            if settings.public_footage_analysis_enabled:
                try:
                    clip = provider.import_public(player, sources, ids, hashes, refs)
                except FootageError as error:
                    notice, blocked = str(error), error.stop_source
        if not clip:
            break
        if (
            clip["id"] in ids
            or clip["content_hash"] in hashes
            or any(overlapping_source(clip, previous) for previous in clips)
        ):
            notice = (
                "The available alternative repeated the same footage; it was not analyzed again."
            )
            ids.add(clip["id"])
            hashes.add(clip["content_hash"])
            if clip.get("source_ref"):
                refs.add(source_key(clip))
            continue
        clips.append(clip)
        ids.add(clip["id"])
        hashes.add(clip["content_hash"])
        if clip.get("source_ref"):
            refs.add(source_key(clip))
    public_sources = [
        {k: v for k, v in source.items() if not k.startswith("_")} for source in (sources or [])
    ]
    if sources is not None:
        job.cp.setdefault("footage_discovery", {})[pid] = {
            "provider": "ESPN",
            "network_requests": (discovery.request_count - start_requests) if discovery else 0,
            "cache_hits": (discovery.cache_hits - start_hits) if discovery else 0,
            "source_links": [s["url"] for s in public_sources],
            "imported_clip_id": clips[0]["id"] if clips else None,
            "prepared_clip_ids": [c["id"] for c in clips],
            "roster_context_matched": bool(
                clips and (clips[0].get("source_identity") or {}).get("roster_match")
            ),
        }
    plan = {
        "clips": clips,
        "sources": public_sources,
        "notice": notice if not clips else None,
        "alternative_notice": notice,
        "limit": limit,
    }
    plans[pid] = plan
    job.save()
    return plan


def identity_checks(job, spark, player, clips):
    """One vision request prechecks both clips; fallback reuses these checks."""
    pid = player["id"]
    saved = job.cp.setdefault("clip_identity_checks", {})
    if pid in saved:
        return saved[pid]
    if len(clips) < 2 or job.mode == "mock" or job.remaining_calls() < 2:
        return {}
    images, evidence = [], []
    for clip in clips:
        payload = verification_payload(player, clip)
        payload["image_frames"] = [
            {"image_index": len(images) + i, "source_frame": f["frame"], "time": f["time"]}
            for i, f in enumerate(clip["frames"])
        ]
        evidence.append({"clip_id": clip["id"], "evidence": payload})
        images.extend(f["url"] for f in clip["frames"])
    job.event(
        "VERIFYING",
        "Muse Spark",
        f"Checking {player['name']}'s identity separately in {len(clips)} clips, with one request.",
    )
    checks = spark.reason(
        "verify_clips",
        {
            "player": player,
            "clips": evidence,
            "instruction": "Return exactly one verification for each supplied clip_id. Treat every clip independently using only its mapped images and dated roster. Source frame indices restart for EACH clip. Never transfer jersey readings, coordinates or identity certainty between clips. Follow each clip's verification and identity requirements, including per-object seed frames. Per clip, return at most three brief identity observations. If named identity is uncertain, keep verified=false but seed clearly visible people as unknown. Explicitly inspect for a visible basketball across each clip's frames and seed id 15 when seen. Keep reasons to one sentence; do not infer unreadable jerseys.",
        },
        ClipIdentityChecks,
        images,
    )
    ids = [c.clip_id for c in checks.clips]
    if len(ids) != len(set(ids)) or set(ids) != {c["id"] for c in clips}:
        raise ModelError(
            "Clip identity checks did not cover exactly the requested clips. The paid request was not repeated."
        )
    saved[pid] = {c.clip_id: c.verification.model_dump() for c in checks.clips}
    job.save()
    return saved[pid]


def usable_evidence(candidate):
    return (
        candidate["verified"]
        and candidate["tracking_accepted"]
        and any(m["value"] is not None and m["evidence_frames"] for m in candidate["metrics"])
    )


def trial_summary(candidate, index, selected):
    clip = candidate.get("clip") or {}
    if not clip:
        outcome, reason = (
            "source_unavailable",
            candidate.get("footage_notice") or "No eligible footage was available.",
        )
    elif candidate.get("footage_notice") and "call budget" in candidate["footage_notice"]:
        outcome, reason = "budget_limit", candidate["footage_notice"]
    elif not candidate["verified"]:
        outcome = "identity_unclear"
        verification = candidate.get("verification") or {}
        if not verification.get("verified") or verification.get("confidence", 0) < 0.75:
            reason = verification.get("reason") or "Player identity was uncertain."
        else:
            reason = "; ".join(
                (candidate.get("identity") or {}).get("reasons", [])
            ) or verification.get("reason", "Player identity was uncertain.")
    elif not candidate["tracking_accepted"]:
        outcome, reason = "tracking_unclear", (candidate.get("critiques") or [{}])[-1].get(
            "explanation", "Tracking did not meet the reliability threshold."
        )
    elif not usable_evidence(candidate):
        outcome, reason = (
            "no_usable_metrics",
            "The clip did not provide reliable observations for a supported film measurement.",
        )
    else:
        outcome, reason = (
            "usable",
            "Identity, tracking and measured film evidence passed the checks.",
        )
    return {
        "number": index + 1,
        "clip_id": clip.get("id"),
        "source_ref": clip.get("source_ref"),
        "source_title": clip.get("source_title"),
        "source_span": clip.get("source_span"),
        "game_date": clip.get("game_date"),
        "quality": candidate["quality"],
        "outcome": outcome,
        "reason": reason,
        "selected": selected,
    }


def scan_player(job, spark, sam, player, mock, provider, discovery, progress):
    plan = clip_plan(job, player, mock, provider, discovery, progress)
    clips = plan["clips"] or [None]
    checks = identity_checks(job, spark, player, plan["clips"])
    trials = job.cp.setdefault("clip_trials", {}).setdefault(player["id"], [])
    stop = "no_clear_clip"
    for index, clip in enumerate(clips):
        if index < len(trials):
            candidate = trials[index]
        else:
            verification = (
                ClipVerification.model_validate(checks[clip["id"]])
                if clip and clip["id"] in checks
                else None
            )
            if index:
                # Reserve one model call for the final report. A prechecked
                # rejected identity is safe to record without tracking calls.
                needed = (
                    0
                    if verification
                    and (not verification.verified or verification.confidence < 0.75)
                    and not verification.objects
                    else 2 if verification else 3
                )
                if job.remaining_calls() < needed + 1:
                    stop = "budget_limit"
                    job.event(
                        "FINDING_CLIPS",
                        "TapeGrade",
                        "Another clip is available, but the remaining call budget is reserved for the final report.",
                    )
                    break
                prior = trial_summary(trials[-1], index - 1, False)
                job.event(
                    "SWITCHING_CLIPS",
                    "TapeGrade",
                    f"{player['name']}'s previous clip was unclear. Automatically checking a different clip ({index+1} of {len(clips)}).",
                    detail={
                        "player_id": player["id"],
                        "previous_clip_id": prior["clip_id"],
                        "clip_id": clip["id"],
                        "reason": prior["outcome"],
                    },
                )
            candidate = analyze_clip(
                job,
                spark,
                sam,
                player,
                clip,
                mock,
                plan["sources"],
                plan["notice"],
                verification=verification,
                clip_index=index,
                allow_sam_retries=index == len(clips) - 1,
            )
            trials.append(candidate)
            job.save()
        if usable_evidence(candidate):
            stop = "usable_clip"
            break
        if (candidate.get("footage_notice") or "").find("call budget") >= 0:
            stop = "budget_limit"
            break
    selected_index = max(
        range(len(trials)),
        key=lambda i: (
            bool(usable_evidence(trials[i])),
            trials[i]["verified"],
            trials[i]["quality"],
        ),
    )
    result = dict(trials[selected_index])
    if stop == "no_clear_clip" and len(clips) == 1:
        stop = "clip_limit" if plan["limit"] == 1 else "no_alternative"
    count = len(trials)
    if stop == "usable_clip":
        notice = (
            f"Automatically switched footage and used clip {selected_index+1} after an earlier clip was unclear."
            if selected_index > 0
            else None
        )
    elif stop == "budget_limit":
        notice = "The call limit was preserved. Another full clip analysis could not fit alongside the final report."
    elif stop == "no_alternative":
        notice = "No different eligible recent clip was available. Uncertain measurements remain withheld."
    elif stop == "clip_limit":
        notice = "The configured clip limit was reached. Uncertain measurements remain withheld."
    else:
        notice = f"Reviewed {count} different clips; none provided clear enough measured film evidence. The report retains the best available clip and withholds unsupported measurements."
    result["clip_attempts"] = [
        trial_summary(c, i, i == selected_index) for i, c in enumerate(trials)
    ]
    result["clip_fallback"] = {
        "limit": plan["limit"],
        "attempted": count,
        "tried_alternative": count > 1,
        "selected_clip_id": (result.get("clip") or {}).get("id"),
        "stop_reason": stop,
        "notice": notice,
        "same_highlight_excerpts": count > 1
        and len({(c.get("clip") or {}).get("source_ref") for c in trials}) == 1,
    }
    return result
