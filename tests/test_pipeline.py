import copy
import time

from sqlalchemy import func, select

from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import (
    CalculatedMetric,
    ModelCall,
    PerceptionLog,
    ScanRun,
    SegmentationResult,
    Verdict,
)
from backend.models.mock import MockSpark
from backend.worker.scan import claim, enqueue, process, run_once


def finished(store, instruction="Find me an undervalued guard."):
    sid = enqueue(instruction, factory=store)
    assert run_once(store)
    with session_scope(store) as s:
        run = s.get(ScanRun, sid)
        assert run.stage == "COMPLETED", run.error
        return sid, run.result


def test_full_demo_metrics_recommendation_and_card(store):
    sid, result = finished(store)
    c = result["candidates"][0]
    assert result["simulated"] is True
    assert c["player"]["id"] == "c1"
    assert [x["quality_score"] for x in c["critiques"]] == [0.46, 0.91]
    assert c["tracking"]["prompt"] == "cream basketball jersey number 4"
    assert [v["verdict"]["verdict"] for v in result["candidates"]] == ["ADD", "MONITOR", "PASS"]
    assert result["staged_move"]["drop_player"]["id"] == "r5"
    assert result["staged_move"]["faab_bid"] == 8
    assert not result["staged_move"]["executed"]
    from backend.services.clips import local_path
    from PIL import Image

    assert Image.open(local_path(result["card"]["url"])).size == (1080, 1350)
    with session_scope(store) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(CalculatedMetric)
                .where(CalculatedMetric.scan_id == sid)
            )
            == 12
        )
        assert (
            s.scalar(
                select(func.count()).select_from(PerceptionLog).where(PerceptionLog.scan_id == sid)
            )
            == 4
        )
        for candidate in result["candidates"]:
            rows = s.scalars(
                select(CalculatedMetric).where(
                    CalculatedMetric.scan_id == sid,
                    CalculatedMetric.player_id == candidate["player"]["id"],
                )
            ).all()
            measured = {
                r.name for r in rows if r.data["value"] is not None and r.data["evidence_frames"]
            }
            assert set(candidate["verdict"]["metric_refs"]) <= measured
            assert "75%" in c["verdict"]["rationale"]


def test_repeated_scan_uses_persistent_cache(store):
    sid, result = finished(store)
    with session_scope(store) as s:
        before = s.scalar(select(func.count()).select_from(ModelCall))
    sid2, result2 = finished(store)
    with session_scope(store) as s:
        assert s.scalar(select(func.count()).select_from(ModelCall)) == before
        assert s.get(ScanRun, sid2).live_calls == 0
        assert s.scalar(select(func.count()).select_from(SegmentationResult)) == 4
    assert result["staged_move"] == result2["staged_move"]


def test_lease_expiration_resumes_checkpoint_without_duplicate_verdicts(store):
    sid, result = finished(store)
    with session_scope(store) as s:
        run = s.get(ScanRun, sid)
        original_attempts = run.attempts
        run.stage = "DECIDING"
        run.lease_until = time.time() - 1
        run.result = None
    assert run_once(store)
    with session_scope(store) as s:
        run = s.get(ScanRun, sid)
        assert run.stage == "COMPLETED"
        assert run.attempts == original_attempts + 1
        assert run.result["staged_move"] == result["staged_move"]
        assert (
            s.scalar(select(func.count()).select_from(Verdict).where(Verdict.scan_id == sid)) == 3
        )


def test_claim_is_exclusive_until_lease_expires(store):
    sid = enqueue("Find a guard", factory=store)
    first = claim(store)
    assert first[0] == sid
    assert claim(store) is None
    with session_scope(store) as s:
        s.get(ScanRun, sid).lease_until = 0
    second = claim(store)
    assert second[0] == sid and second[1] != first[1]


def test_retry_limit_and_no_strong_move_on_bad_tracking(store, monkeypatch):
    original = MockSpark.reason

    def bad(self, operation, payload, schema, images=None):
        result = original(self, operation, payload, schema, images)
        if operation == "critic":
            result.quality_score = 0.2
            result.retry_justified = True
            result.refined_prompt = f'cream jersey number 4 detail {payload["attempt"]}'
        return result

    monkeypatch.setattr(MockSpark, "reason", bad)
    monkeypatch.setattr(settings, "max_candidates", 1)
    _, result = finished(store)
    assert len(result["candidates"][0]["critiques"]) == 3
    assert result["staged_move"] is None
    assert all(m["value"] is None for m in result["candidates"][0]["metrics"])


def test_worker_mode_mismatch_does_not_fallback(store, monkeypatch):
    sid = enqueue("Find guard", factory=store)
    monkeypatch.setattr(settings, "mock_models", False)
    assert run_once(store)
    with session_scope(store) as s:
        run = s.get(ScanRun, sid)
        assert run.stage == "FAILED" and "mode" in run.error
        assert run.result is None and run.live_calls == 0
