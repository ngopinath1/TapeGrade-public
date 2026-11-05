"""One-clip live diagnostic using the existing durable jobs, caches and model clients.

This deliberately has no fantasy decision agent: video-only subjects have no
licensed statistics or roster membership. Four initial calls maximum; explicit
failed-job continuations are capped at six total. No automatic tracking retry.
"""

from hashlib import sha256
import json

from sqlalchemy import select

from backend.api.types import ClipVerification, Criticism, Tracking
from backend.agents.critic import PerceptionCritic
from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import (
    CalculatedMetric,
    JobEvent,
    PerceptionLog,
    Player,
    ScanRun,
    SegmentationResult,
    Verdict,
    now,
)
from backend.models.base import ModelError
from backend.services.clips import usable_upload
from backend.services.metrics import calculate_metrics
from backend.services.overlays import create_overlays
from backend.services.tape_card import render_card


def enqueue_film(player: dict, clip: dict, factory=None):
    if settings.mock_models:
        raise ModelError("Film diagnostics require explicit MOCK_MODELS=0; no simulated fallback.")
    if not player.get("film_only") or player.get("is_demo") or clip.get("is_demo"):
        raise ModelError(
            "A film diagnostic needs an actual uploaded clip and a video-only subject."
        )
    if not usable_upload(clip) or clip["duration"] > 5 or clip["player_id"] != player["id"]:
        raise ModelError("Diagnostic clip is missing, too long, or belongs to another subject.")
    key = (
        "film-v1-"
        + sha256(
            json.dumps(
                {
                    "hash": clip["content_hash"],
                    "player": player,
                    "spark": settings.spark_model,
                    "sam": settings.sam_model,
                    "image": settings.image_model,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
    )
    with session_scope(factory) as s:
        previous = s.scalar(select(ScanRun).where(ScanRun.request_key == key))
        if previous:
            return previous.id
        if not s.get(Player, player["id"]):
            raise ModelError("Register the video-only subject before enqueuing its diagnostic.")
        row = ScanRun(
            league_id="demo-nba",
            mode="live",
            source="film-test",
            request_key=key,
            instruction=f"Film diagnostic: {player['name']}. No fantasy transaction or invented statistics.",
            checkpoint={"film_test": True, "player": player, "clip": clip},
        )
        s.add(row)
        s.flush()
        s.add(
            JobEvent(
                scan_id=row.id,
                stage="QUEUED",
                actor="TapeGrade",
                message="User-authorized film diagnostic queued: four calls maximum; no automatic retry.",
            )
        )
        return row.id


def report(job):
    return {
        "film_test": True,
        "simulated": False,
        "league_is_demo": True,
        "candidates": [job.cp["candidate"]],
        "staged_move": None,
        "card": job.cp.get("card"),
        "card_error": job.cp.get("card_error"),
        "guardrail_notice": "Film diagnostic only. No verified fantasy statistics or roster membership; no transaction recommended.",
        "shortlist": {
            "roster_need": "Film diagnostic",
            "reasoning": "User-selected excerpt; no fantasy shortlisting performed.",
        },
    }


def retry_film(scan_id: str, additional_calls: int = 2, factory=None):
    """Explicit continuation only; never scheduled or automatically invoked."""
    with session_scope(factory) as s:
        row = s.get(ScanRun, scan_id)
        if not row or row.stage != "FAILED" or not row.checkpoint.get("film_test"):
            raise ModelError("Only a failed film diagnostic can be explicitly continued.")
        if not 1 <= additional_calls <= 2 or row.live_calls + additional_calls > 6:
            raise ModelError("Continuation permits at most two additional calls and six total.")
        cp = dict(row.checkpoint)
        cp["film_call_limit"] = row.live_calls + additional_calls
        row.checkpoint = cp
        row.stage, row.error, row.lease_until = "QUEUED", None, 0
        s.add(
            JobEvent(
                scan_id=row.id,
                stage="QUEUED",
                actor="TapeGrade",
                message=f"Explicit manual continuation: at most {additional_calls} additional model calls, {cp['film_call_limit']} total. Saved tracking and successful outputs are retained.",
            )
        )


def save(job):
    job.save()
    with session_scope(job.factory) as s:
        s.get(ScanRun, job.id).result = report(job)


def process_film(job):
    from backend.worker.scan import CachedSpark
    from backend.models.muse_spark import MuseSpark
    from backend.models.sam import SAMClient, seed_prompt
    from backend.models.muse_image import MuseImage

    if settings.mock_models or job.mode != "live":
        raise ModelError("Film diagnostic cannot substitute simulated models.")
    player, clip = job.cp["player"], job.cp["clip"]
    spark = CachedSpark(job, MuseSpark())
    candidate = job.cp.setdefault(
        "candidate",
        {
            "player": player,
            "clip": clip,
            "verified": False,
            "quality": 0,
            "tracking": None,
            "metrics": [],
            "critiques": [],
            "overlays": [],
            "verdict": {
                "player_id": player["id"],
                "verdict": "MONITOR",
                "confidence": 0,
                "rationale": "Film diagnostic pending. No fantasy recommendation.",
                "strengths": [],
                "weaknesses": ["No fantasy statistics supplied."],
                "metric_refs": [],
            },
        },
    )
    save(job)
    frames = [f["url"] for f in clip["frames"][::2]]
    if "verification" not in candidate:
        job.event(
            "VERIFYING",
            "Muse Spark",
            "Verifying the visible jersey target and frame-zero seed boxes.",
            15,
        )
        verification = spark.reason(
            "verify",
            {
                "player": player,
                "clip": clip,
                "instruction": "Video-only diagnostic, not a claim about real-name identity, game date, or fantasy value. Verify the supplied visible team/jersey description. Require one frame-zero target id 1. Add up to 3 clearly visible opposing defenders id 2+ and ball id 15 only if visible. All boxes are inclusive source pixels. Do not identify referees, teammates, crowd, or bench as defenders. Abstain if the described target is absent. Keep the explanation concise.",
            },
            ClipVerification,
            frames,
        )
        candidate["verification"] = verification.model_dump()
        candidate["verified"] = verification.verified and verification.confidence >= 0.75
        save(job)
    verification = ClipVerification.model_validate(candidate["verification"])
    if not candidate["verified"]:
        candidate["verdict"]["rationale"] = "Clip rejected: " + verification.reason
        job.cp["card_error"] = "No verified target; SAM and image calls skipped."
        job.event("VERIFYING", "Muse Spark", candidate["verdict"]["rationale"], 90)
    else:
        objects = [obj.model_dump() for obj in verification.objects]
        prompt = seed_prompt(clip, objects)
        if candidate["tracking"] is None:
            job.event(
                "TRACKING",
                "SAM 3.1",
                "Tracking the four-second real-video excerpt. One attempt only.",
                35,
                {"prompt": prompt, "simulated": False, "attempt": 0},
            )
            payload = {
                "clip_hash": clip["content_hash"],
                "prompt": prompt,
                "objects": objects,
                "mask_encoding": "one_bit",
            }
            track = job.cached(
                settings.sam_model,
                "tracking",
                payload,
                lambda: SAMClient().track(clip, prompt, objects).model_dump(),
            )
            candidate["tracking"] = track
            key = sha256(
                json.dumps({"mode": "live", **payload}, sort_keys=True).encode()
            ).hexdigest()
            with session_scope(job.factory) as s:
                if not s.scalar(
                    select(SegmentationResult).where(SegmentationResult.cache_key == key)
                ):
                    s.add(
                        SegmentationResult(
                            cache_key=key,
                            clip_id=clip["id"],
                            model=settings.sam_model,
                            mode="live",
                            data=track,
                        )
                    )
            save(job)
        tracking = Tracking.model_validate(candidate["tracking"])
        if not candidate["overlays"]:
            candidate["overlays"] = create_overlays(clip, tracking, "film-" + job.id)
            save(job)
        if not candidate["critiques"]:
            job.event(
                "CRITIQUING",
                "Muse Spark",
                "Comparing original frames with actual SAM masks and boxes.",
                60,
            )
            critique = PerceptionCritic(spark).inspect(
                player["id"], 0, tracking, frames + candidate["overlays"][::2]
            )
            candidate["critiques"] = [{"attempt": 0, "prompt": prompt, **critique.model_dump()}]
            with session_scope(job.factory) as s:
                previous = s.scalar(
                    select(PerceptionLog).where(
                        PerceptionLog.scan_id == job.id,
                        PerceptionLog.player_id == player["id"],
                        PerceptionLog.attempt == 0,
                    )
                )
                if not previous:
                    s.add(
                        PerceptionLog(
                            scan_id=job.id,
                            player_id=player["id"],
                            attempt=0,
                            data=candidate["critiques"][0],
                        )
                    )
            save(job)
        critique = Criticism.model_validate(
            {k: v for k, v in candidate["critiques"][0].items() if k not in ("attempt", "prompt")}
        )
        candidate["quality"] = min(verification.confidence, critique.quality_score)
        accepted = candidate["quality"] >= settings.perception_quality_threshold
        job.event(
            "CRITIQUING",
            "Muse Spark",
            f"Tracking {'accepted' if accepted else 'unreliable'} ({candidate['quality']:.0%}). "
            + (
                "Critic requested a retry; this budget-limited diagnostic stops after one SAM call."
                if critique.retry_justified and not accepted
                else "No forced retry."
            ),
            70,
            critique.model_dump(),
        )
        job.event(
            "CALCULATING_METRICS",
            "TapeGrade",
            "Calculating observed screen-space proxies; unsupported metrics stay unavailable.",
            75,
        )
        candidate["metrics"] = [
            m.model_dump() for m in calculate_metrics(tracking, candidate["quality"])
        ]
        measured = [m for m in candidate["metrics"] if m["value"] is not None]
        candidate["verdict"] = {
            "player_id": player["id"],
            "verdict": "MONITOR",
            "confidence": candidate["quality"],
            "rationale": "Film diagnostic only. "
            + critique.explanation
            + " No fantasy transaction: statistics and roster membership unavailable.",
            "strengths": [
                f"{m['label']}: {m['value']}{m['unit']} (screen-space proxy)." for m in measured
            ],
            "weaknesses": [
                "Short highlight selection; not representative of full-game opportunity.",
                "No verified statistics, game date, or fantasy eligibility supplied.",
            ]
            + critique.identity_swaps
            + critique.incorrect_masks,
            "metric_refs": [m["name"] for m in measured],
        }
        save(job)
        if "card" not in job.cp and "card_error" not in job.cp:
            job.event(
                "GENERATING_CARD",
                "Muse Image",
                "Generating one diagnostic Tape Card background; observed metrics and labels composited locally.",
                85,
            )
            try:
                job.cp["card"] = {
                    **render_card(
                        player,
                        candidate["verdict"],
                        candidate["metrics"],
                        clip,
                        False,
                        MuseImage(job),
                        diagnostic={
                            "quality": candidate["quality"],
                            "observed_frames": len(tracking.frames),
                        },
                    ),
                    "player_id": player["id"],
                }
            except ModelError as error:
                job.cp["card_error"] = str(error)
                job.event("GENERATING_CARD", "Muse Image", "Card unavailable: " + str(error))
            save(job)
    with session_scope(job.factory) as s:
        for metric in candidate["metrics"]:
            previous = s.scalar(
                select(CalculatedMetric).where(
                    CalculatedMetric.scan_id == job.id,
                    CalculatedMetric.player_id == player["id"],
                    CalculatedMetric.name == metric["name"],
                )
            )
            if not previous:
                s.add(
                    CalculatedMetric(
                        scan_id=job.id, player_id=player["id"], name=metric["name"], data=metric
                    )
                )
        previous = s.scalar(
            select(Verdict).where(Verdict.scan_id == job.id, Verdict.player_id == player["id"])
        )
        if not previous:
            s.add(Verdict(scan_id=job.id, player_id=player["id"], data=candidate["verdict"]))
        row = s.get(ScanRun, job.id)
        row.result, row.stage, row.progress, row.error, row.lease_until = (
            report(job),
            "COMPLETED",
            100,
            None,
            0,
        )
        row.updated_at = now()
        s.add(
            JobEvent(
                scan_id=job.id,
                stage="COMPLETED",
                actor="TapeGrade",
                message="Film diagnostic complete. No fantasy transaction generated or executed.",
            )
        )
