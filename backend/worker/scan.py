"""Durable single-job worker with atomic leases and replay-safe checkpoints.

Run as a separate process. HTTP requests enqueue jobs; they never run inference.
Expired leases are claimable after a crash. Model and segmentation caches survive
process restarts. A timed-out external request may have been billed; we do not
automatically retry paid network calls within one operation.
"""

import argparse
from hashlib import sha256
import json
import logging
import time
from uuid import uuid4

from sqlalchemy import select, update

from backend.agents.decision import DecisionAgent
from backend.agents.scout import ScoutAgent
from backend.api.types import Decision
from backend.config import settings
from backend.db.database import Session, initialize, session_scope
from backend.db.schema import (
    CalculatedMetric,
    JobEvent,
    ModelCache,
    ModelCall,
    ScanRun,
    StagedMove,
    Verdict,
    now,
)
from backend.models.base import ModelError
from backend.models.mock import MockSAM, MockSpark
from backend.services.state import get_guardrails, get_league, seed_demo
from backend.services.scan_readiness import scan_readiness
from backend.services.scan_workflow import PreparationPending
from backend.services.tape_card import render_card

log = logging.getLogger("tapegrade.worker")
TERMINAL = ("COMPLETED", "FAILED")


def enqueue(instruction, source="manual", request_key=None, factory=None, prepare=False):
    with session_scope(factory) as s:
        league = get_league(factory)
        if request_key:
            existing = s.scalar(select(ScanRun).where(ScanRun.request_key == request_key))
            if existing:
                if existing.league_id != league["id"]:
                    raise ModelError(
                        "Idempotency key belongs to a different league. Use a new key."
                    )
                return existing.id
        automatic = prepare and not league.get("is_demo", True)
        if automatic:
            from backend.services.scan_workflow import workflow_status

            workflow = workflow_status(league)
            readiness, available = {"blockers": workflow["blockers"], "notice": None}, league[
                "available"
            ]
        else:
            readiness, available = scan_readiness(
                league, get_guardrails(factory, league["id"]), factory
            )
        if readiness["blockers"]:
            raise ModelError(" ".join(readiness["blockers"]))
        league = {**league, "available": available, "scan_readiness": readiness}
        # Deterministic narrowing happens before any model input. Keep source IDs.
        if not league.get("is_demo", True):
            league = {
                **league,
                "available": sorted(
                    league["available"],
                    key=lambda p: (-(p.get("recent_fantasy_average") or 0), p["id"]),
                )[:12],
            }
        run = ScanRun(
            league_id=league["id"],
            instruction=instruction,
            mode="mock" if settings.mock_models else "live",
            source=source,
            request_key=request_key,
            checkpoint={
                "league": league,
                "candidates": [],
                "max_candidates": settings.max_candidates,
                "max_clips_per_candidate": settings.max_clips_per_candidate,
                "max_sam_retries": settings.max_sam_retries,
                "live_call_limit": settings.max_live_model_calls_per_scan,
                "automatic_preparation": automatic,
            },
        )
        s.add(run)
        s.flush()
        s.add(
            JobEvent(
                scan_id=run.id,
                stage="QUEUED",
                actor="TapeGrade",
                message=readiness["notice"] or "Scan queued for the separate worker.",
            )
        )
        return run.id


def claim(factory=None, scan_id=None):
    token = uuid4().hex
    with session_scope(factory) as s:
        eligible = (
            ScanRun.stage.notin_(TERMINAL),
            ScanRun.lease_until < time.time(),
            *([ScanRun.id == scan_id] if scan_id else []),
        )
        run = s.scalar(select(ScanRun).where(*eligible).order_by(ScanRun.created_at).limit(1))
        if not run:
            return None
        result = s.execute(
            update(ScanRun)
            .where(ScanRun.id == run.id, *eligible)
            .values(
                worker_token=token,
                lease_until=time.time() + settings.job_lease_seconds,
                attempts=ScanRun.attempts + 1,
            )
        )
        return (run.id, token) if result.rowcount == 1 else None


class Job:
    def __init__(self, scan_id, token, factory=None):
        self.id, self.token, self.factory = scan_id, token, factory
        with session_scope(factory) as s:
            run = s.get(ScanRun, scan_id)
            self.mode, self.instruction, self.cp = run.mode, run.instruction, dict(run.checkpoint)
            self.league_id = run.league_id

    def heartbeat(self):
        with session_scope(self.factory) as s:
            result = s.execute(
                update(ScanRun)
                .where(ScanRun.id == self.id, ScanRun.worker_token == self.token)
                .values(lease_until=time.time() + settings.job_lease_seconds, updated_at=now())
            )
            if result.rowcount != 1:
                raise ModelError("Worker lease lost; this process stopped safely.")

    def event(self, stage, actor, message, progress=None, detail=None):
        self.heartbeat()
        with session_scope(self.factory) as s:
            run = s.get(ScanRun, self.id)
            run.stage, run.updated_at = stage, now()
            if progress is not None:
                run.progress = progress
            s.add(
                JobEvent(
                    scan_id=self.id, stage=stage, actor=actor, message=message, detail=detail or {}
                )
            )

    def save(self):
        self.heartbeat()
        with session_scope(self.factory) as s:
            s.get(ScanRun, self.id).checkpoint = json.loads(json.dumps(self.cp))

    def remaining_calls(self):
        if self.mode == "mock":
            return 1000000
        with session_scope(self.factory) as s:
            run = s.get(ScanRun, self.id)
            limit = min(
                settings.max_live_model_calls_per_scan,
                self.cp.get("live_call_limit", settings.max_live_model_calls_per_scan),
            )
            if self.cp.get("film_test"):
                limit = min(limit, self.cp.get("film_call_limit", 4))
            return max(0, limit - run.live_calls)

    def reserve_call(self, model, operation):
        self.heartbeat()
        with session_scope(self.factory) as s:
            run = s.get(ScanRun, self.id)
            limit = (
                min(settings.max_live_model_calls_per_scan, self.cp.get("film_call_limit", 4))
                if self.cp.get("film_test")
                else min(
                    settings.max_live_model_calls_per_scan,
                    self.cp.get("live_call_limit", settings.max_live_model_calls_per_scan),
                )
            )
            if run.live_calls >= limit:
                raise ModelError(
                    "Live model call budget reached. Reduce candidates or increase the explicit scan budget."
                )
            run.live_calls += 1

    def cached(self, model, operation, payload, call):
        key = sha256(
            json.dumps(
                {
                    "version": 2,
                    "mode": self.mode,
                    "model": model,
                    "operation": operation,
                    "payload": payload,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        with session_scope(self.factory) as s:
            hit = s.get(ModelCache, key)
            if hit:
                s.add(
                    JobEvent(
                        scan_id=self.id,
                        stage=s.get(ScanRun, self.id).stage,
                        actor=model,
                        message=f"{operation}: reused cached output.",
                        detail={"cache_key": key},
                    )
                )
                return hit.data
        self.heartbeat()
        if self.mode == "live":
            self.reserve_call(model, operation)
        start = time.monotonic()
        try:
            data = call()
        except Exception:
            with session_scope(self.factory) as s:
                s.add(
                    ModelCall(
                        scan_id=self.id,
                        model=model,
                        operation=operation,
                        status="failed",
                        duration_ms=int((time.monotonic() - start) * 1000),
                    )
                )
            raise
        with session_scope(self.factory) as s:
            if not s.get(ModelCache, key):
                s.add(ModelCache(key=key, mode=self.mode, model=model, data=data))
            s.add(
                ModelCall(
                    scan_id=self.id,
                    model=model,
                    operation=operation,
                    status="simulated" if self.mode == "mock" else "completed",
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            )
        return data


class CachedSpark:
    def __init__(self, job, raw):
        self.job, self.raw = job, raw

    def reason(self, operation, payload, schema, images=None):
        model = settings.spark_model
        data = self.job.cached(
            model,
            operation,
            {
                "input": payload,
                "images": images or [],
                "schema": schema.model_json_schema(),
                "inference_config": {
                    "max_completion_tokens": settings.spark_max_completion_tokens,
                    "reasoning_effort": settings.spark_reasoning_effort,
                },
            },
            lambda: self.raw.reason(operation, payload, schema, images).model_dump(),
        )
        return schema.model_validate(data)


def process(scan_id, token, factory=None):
    job = Job(scan_id, token, factory)
    mock = job.mode == "mock"
    try:
        if mock != settings.mock_models:
            raise ModelError(
                "Job model mode differs from worker configuration. Restart with the original mode or create a new scan."
            )
        if job.cp.get("film_test"):
            from backend.worker.film import process_film

            process_film(job)
            return
        if job.cp.get("automatic_preparation"):
            from backend.services.scan_workflow import prepare_live_scan

            prepare_live_scan(job)
        if mock:
            raw_spark, sam, image = MockSpark(), MockSAM(), None
        else:
            from backend.models.muse_spark import MuseSpark
            from backend.models.sam import SAMClient
            from backend.models.muse_image import MuseImage

            raw_spark, sam, image = MuseSpark(), SAMClient(), MuseImage(job)
        spark = CachedSpark(job, raw_spark)
        from backend.providers.footage import (
            AutomaticClipProvider,
            ESPNFootageDiscovery,
        )

        automatic_clips = (
            AutomaticClipProvider(factory) if job.cp.get("automatic_preparation") else None
        )
        discovery = (
            ESPNFootageDiscovery(force_refresh=bool(job.cp.get("force_footage_discovery")))
            if automatic_clips and settings.footage_discovery_enabled
            else None
        )
        league = job.cp["league"]
        if "shortlist" not in job.cp:
            job.event(
                "SCOUTING",
                "TapeGrade",
                "Selecting players for inspection; the final roster decision comes after the evidence checks.",
                10 if job.cp.get("automatic_preparation") else 5,
            )
            job.cp["shortlist"] = (
                ScoutAgent(spark)
                .shortlist(job.instruction, league, job.cp["max_candidates"])
                .model_dump()
            )
            job.save()
        shortlist = job.cp["shortlist"]["player_ids"]
        completed_ids = {c["player"]["id"] for c in job.cp["candidates"]}
        for index, pid in enumerate(shortlist):
            if pid in completed_ids:
                continue
            player = next(p for p in league["available"] if p["id"] == pid)
            progress = 12 + int(index / max(1, len(shortlist)) * 60)
            from backend.worker.clip_scan import scan_player

            candidate = scan_player(
                job, spark, sam, player, mock, automatic_clips, discovery, progress
            )
            with session_scope(factory) as s:
                for m in candidate["metrics"]:
                    row = s.scalar(
                        select(CalculatedMetric).where(
                            CalculatedMetric.scan_id == scan_id,
                            CalculatedMetric.player_id == pid,
                            CalculatedMetric.name == m["name"],
                        )
                    )
                    if row:
                        row.data = m
                    else:
                        s.add(
                            CalculatedMetric(scan_id=scan_id, player_id=pid, name=m["name"], data=m)
                        )
            job.cp["candidates"].append(candidate)
            job.save()
        from backend.services.observed_players import (
            add_observed_candidates,
            apply_profile_verdicts,
        )

        job.cp["candidates"] = add_observed_candidates(
            job.cp["candidates"], league, get_guardrails(factory, job.league_id)
        )
        job.save()
        job.event(
            "DECIDING",
            "Muse Spark",
            "Combining stored film metrics, sourced statistics and roster guardrails.",
            80,
        )
        candidates = job.cp["candidates"]
        if "decision" in job.cp:
            from backend.services.staging import validate_decision

            decision, staged = validate_decision(
                Decision.model_validate(job.cp["decision"]),
                candidates,
                league["roster"],
                get_guardrails(factory, job.league_id),
                league["faab_remaining"],
                league=league,
            )
        else:
            decision_agent = DecisionAgent(spark)
            decision, staged = (
                decision_agent.decide(
                    job.instruction, league, candidates, get_guardrails(factory, job.league_id)
                )
                if candidates
                else (Decision(verdicts=[], move=None), None)
            )
            job.cp["decision_warnings"] = decision_agent.validation_warnings
            job.cp["decision"] = decision.model_dump()
            job.save()
        for c in candidates:
            c["verdict"] = next(
                v.model_dump() for v in decision.verdicts if v.player_id == c["player"]["id"]
            )
        apply_profile_verdicts(candidates)
        job.cp["candidates"] = candidates
        job.save()
        card, card_error = None, None
        if candidates:
            best = next(
                (c for c in candidates if staged and c["player"]["id"] == staged["add_player_id"]),
                max(
                    (c for c in candidates if c["verified"]),
                    key=lambda c: c["quality"],
                    default=candidates[0],
                ),
            )
            allow_artwork = (
                not job.cp.get("skip_paid_artwork")
                and job.remaining_calls() >= 1
                and (
                    mock
                    or (
                        best["verified"]
                        and best["quality"] >= settings.perception_quality_threshold
                        and best["verdict"]["confidence"]
                        >= get_guardrails(factory, job.league_id).min_confidence
                        and best["verdict"]["verdict"] != "PASS"
                        and any(
                            m["value"] is not None and m["evidence_frames"] for m in best["metrics"]
                        )
                    )
                )
            )
            job.event(
                "GENERATING_CARD",
                "Muse Image" if not mock and allow_artwork else "TapeGrade",
                (
                    "Generating scouting artwork and compositing verified typography."
                    if not mock and allow_artwork
                    else "Rendering the evidence report card."
                ),
                92,
            )
            try:
                card = render_card(
                    best["player"],
                    best["verdict"],
                    best["metrics"],
                    best["clip"] if best["verified"] else None,
                    mock,
                    image,
                    allow_artwork=allow_artwork,
                )
                card["player_id"] = best["player"]["id"]
            except ModelError as e:
                card_error = str(e)
                job.event("GENERATING_CARD", "Muse Image", f"Card unavailable: {e}")
        else:
            card_error = (
                "No supported candidates; image generation skipped to preserve the API budget."
            )
            job.event("GENERATING_CARD", "TapeGrade", card_error)
        # Re-check the latest settings after slow image generation.
        from backend.services.staging import validate_decision

        current_league = get_league(factory, job.league_id)
        before_verdicts = [v.model_dump() for v in decision.verdicts]
        decision, staged = validate_decision(
            decision,
            candidates,
            current_league["roster"],
            get_guardrails(factory, job.league_id),
            current_league["faab_remaining"],
            league=current_league,
        )
        for c in candidates:
            c["verdict"] = next(
                v.model_dump() for v in decision.verdicts if v.player_id == c["player"]["id"]
            )
        apply_profile_verdicts(candidates)
        if card and before_verdicts != [v.model_dump() for v in decision.verdicts]:
            # Updated labels require no further paid artwork request.
            card = render_card(
                best["player"],
                best["verdict"],
                best["metrics"],
                best["clip"] if best["verified"] else None,
                mock,
                allow_artwork=False,
            )
            card["player_id"] = best["player"]["id"]
        job.cp["candidates"] = candidates
        job.save()
        result = {
            "candidates": candidates,
            "shortlist": job.cp["shortlist"],
            "staged_move": staged,
            "card": card,
            "card_error": card_error,
            "simulated": mock,
            "league_is_demo": league.get("is_demo", True),
            "statistics_source": league.get("stats_summary"),
            "scan_notice": league.get("scan_readiness", {}).get("notice"),
            "data_refresh": job.cp.get("data_refresh"),
            "footage_discovery": job.cp.get("footage_discovery", {}),
            "decision_warnings": job.cp.get("decision_warnings", []),
            "guardrail_notice": (
                "The model’s evidence references did not match the verified film measurements. That interpretation was withheld; no roster move is recommended."
                if job.cp.get("decision_warnings")
                else (
                    "No roster move is supported without verified film. Review the player report and footage sources below."
                    if not staged and candidates and not any(c["verified"] for c in candidates)
                    else (
                        "No move cleared the evidence, current player availability and your saved limits."
                        if not staged
                        else None
                    )
                )
            ),
        }
        job.heartbeat()
        with session_scope(factory) as s:
            for c in candidates:
                existing = s.scalar(
                    select(Verdict).where(
                        Verdict.scan_id == scan_id, Verdict.player_id == c["player"]["id"]
                    )
                )
                if existing:
                    existing.data = c["verdict"]
                else:
                    s.add(Verdict(scan_id=scan_id, player_id=c["player"]["id"], data=c["verdict"]))
            move_row = s.scalar(select(StagedMove).where(StagedMove.scan_id == scan_id))
            if staged and not move_row:
                s.add(StagedMove(scan_id=scan_id, data=staged))
            run = s.get(ScanRun, scan_id)
            run.result, run.stage, run.progress, run.error, run.lease_until = (
                result,
                "COMPLETED",
                100,
                None,
                0,
            )
            run.updated_at = now()
            s.add(
                JobEvent(
                    scan_id=scan_id,
                    stage="COMPLETED",
                    actor="TapeGrade",
                    message="Scan complete. Any transaction is a recommendation only.",
                )
            )
        from backend.services.notifications import notify

        notify(scan_id, result)
    except PreparationPending:
        with session_scope(factory) as s:
            run = s.get(ScanRun, scan_id)
            if run.worker_token == token:
                run.lease_until = time.time() + 2
    except Exception as e:
        # Never send raw HTTP exceptions (which can carry credential-bearing bodies) to the UI.
        message = (
            str(e)
            if isinstance(e, (ModelError, ValueError))
            else f"{type(e).__name__}: scan failed; see local worker logs."
        )
        log.error("Scan %s failed (%s)", scan_id, type(e).__name__)
        with session_scope(factory) as s:
            run = s.get(ScanRun, scan_id)
            if run.worker_token == token:
                run.stage, run.error, run.lease_until, run.updated_at = "FAILED", message, 0, now()
                s.add(JobEvent(scan_id=scan_id, stage="FAILED", actor="TapeGrade", message=message))
    finally:
        if "discovery" in locals() and discovery:
            discovery.close()


def run_once(factory=None):
    from backend.worker.stats import run_once as refresh_once

    if refresh_once(factory):
        return True
    claimed = claim(factory)
    if claimed:
        process(*claimed, factory)
    return bool(claimed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--scan-id", help="Process only this scan, without draining unrelated jobs."
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    initialize()
    seed_demo()
    if args.scan_id:
        claimed = claim(scan_id=args.scan_id)
        if claimed:
            process(*claimed)
        return
    if args.once:
        run_once()
        return
    from backend.worker.scheduler import start_scheduler

    scheduler = start_scheduler()
    log.info(
        "Worker started · %s models · scheduler %s",
        "mock" if settings.mock_models else "live",
        bool(scheduler),
    )
    try:
        while True:
            if not run_once():
                time.sleep(settings.worker_poll_seconds)
    except KeyboardInterrupt:
        if scheduler:
            scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
