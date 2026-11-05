"""Offline live-worker contracts. Fake clients consume no external API credits."""

from copy import deepcopy
from types import SimpleNamespace

from pydantic import SecretStr
import pytest
from sqlalchemy import select

from backend.api.types import Tracking
from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import Clip, ModelCall, PerceptionLog, ScanRun
from backend.models.base import ModelError
from backend.providers.footage import AutomaticClipProvider, FootageError
from backend.services.clips import LocalClipProvider, prepare_clip
from backend.services.sample import ensure_sample
from backend.services.state import get_league
from backend.worker import scan


@pytest.fixture
def fallback(store, monkeypatch):
    monkeypatch.setattr(settings, "max_candidates", 1)
    monkeypatch.setattr(settings, "max_clips_per_candidate", 2)
    monkeypatch.setattr(settings, "max_sam_retries", 0)
    monkeypatch.setattr(settings, "max_live_model_calls_per_scan", 6)
    player = get_league(store)["available"][0]
    older = prepare_clip(ensure_sample("c1"), player["id"], False, store)
    newer = prepare_clip(ensure_sample("c2"), player["id"], False, store)
    first = LocalClipProvider(False, store).find(player["id"])
    second = next(c for c in [older, newer] if c["id"] != first["id"])
    case = SimpleNamespace(
        first=first,
        second=second,
        tracked=[],
        operations=[],
        bad_first=True,
        both_bad=False,
        identity_bad=False,
        no_observations=False,
        transport_failure=False,
        invalid_batch=False,
        scene_only=False,
        critics=0,
    )
    objects = [
        {"id": 1, "role": "target", "box": [100, 200, 140, 300]},
        {"id": 2, "role": "defender", "box": [300, 200, 340, 300]},
        {"id": 15, "role": "ball", "box": [110, 240, 120, 250]},
    ]

    def verified(clip_id):
        good = not case.scene_only and not (case.identity_bad and clip_id == first["id"])
        return {
            "verified": good,
            "confidence": 0.96 if good else 0.2,
            "reason": (
                "OFFLINE fixture identity clear" if good else "OFFLINE fixture jersey unreadable"
            ),
            "target_description": "OFFLINE fixture target",
            "objects": objects if good or case.scene_only else [],
        }

    class Spark:
        def reason(self, operation, payload, schema, images=None):
            case.operations.append(operation)
            if operation == "verify_clips":
                assert len(payload["clips"]) == 2 and len(images) == 10
                assert [
                    f["image_index"] for f in payload["clips"][1]["evidence"]["image_frames"]
                ] == list(range(5, 10))
                data = {
                    "clips": [
                        {"clip_id": p["clip_id"], "verification": verified(p["clip_id"])}
                        for p in payload["clips"]
                    ]
                }
                if case.invalid_batch:
                    data["clips"][1]["clip_id"] = "unrequested-clip"
            elif operation == "verify":
                data = verified(payload["clip"]["id"])
            elif operation == "critic":
                case.critics += 1
                if case.transport_failure:
                    raise ModelError("OFFLINE service unavailable; not a footage-quality rejection")
                bad = (case.bad_first and case.critics == 1) or case.both_bad
                data = {
                    "quality_score": 0.4 if bad else 0.92,
                    "identity_swaps": [],
                    "missing_tracking": ["OFFLINE track drift"] if bad else [],
                    "incorrect_masks": [],
                    "occlusion_problems": [],
                    "retry_justified": bad,
                    "refined_prompt": "",
                    "explanation": "OFFLINE unclear track" if bad else "OFFLINE good tracking",
                }
                if case.scene_only:
                    data["object_tracking_checks"] = [
                        {
                            "object_id": o["id"],
                            "quality_score": 0.92,
                            "identity_preserved": True,
                            "role_correct": True,
                            "reason": "OFFLINE visible scene object",
                        }
                        for o in payload["verified_seed_objects"]
                    ]
            elif operation == "decide":
                data = {
                    "verdicts": [
                        {
                            "player_id": c["player"]["id"],
                            "verdict": "MONITOR",
                            "confidence": min(0.8, c["quality"]),
                            "rationale": "OFFLINE conservative report",
                            "strengths": [],
                            "weaknesses": [],
                            "metric_refs": [
                                m["name"] for m in c["metrics"] if m["value"] is not None
                            ],
                        }
                        for c in payload["candidates"]
                    ],
                    "move": None,
                }
            else:
                raise AssertionError(operation)
            return schema.model_validate(data)

    class SAM:
        def track(self, clip, prompt, seeds):
            case.tracked.append(clip["id"])
            visible = objects[:1] if case.no_observations and clip["id"] == first["id"] else objects
            return Tracking.model_validate(
                {
                    "width": clip["width"],
                    "height": clip["height"],
                    "fps": clip["fps"],
                    "prompt": prompt,
                    "simulated": False,
                    "frames": [
                        {
                            "frame": f["frame"],
                            "time": f["time"],
                            "objects": [
                                {
                                    **o,
                                    "centroid": [
                                        (o["box"][0] + o["box"][2]) / 2,
                                        (o["box"][1] + o["box"][3]) / 2,
                                    ],
                                }
                                for o in visible
                            ],
                        }
                        for f in clip["frames"]
                    ],
                }
            )

    sid = scan.enqueue("Review " + player["name"], factory=store)
    with session_scope(store) as s:
        r = s.get(ScanRun, sid)
        r.mode = "live"
        r.checkpoint = {**r.checkpoint, "skip_paid_artwork": True}
    monkeypatch.setattr(settings, "mock_models", False)
    monkeypatch.setattr(settings, "model_api_key", SecretStr("offline-fake-key"))
    monkeypatch.setattr("backend.models.muse_spark.MuseSpark", Spark)
    monkeypatch.setattr("backend.models.sam.SAMClient", SAM)
    case.sid = sid
    return case


def completed(store, case):
    assert scan.run_once(store)
    with session_scope(store) as s:
        r = s.get(ScanRun, case.sid)
        assert r.stage == "COMPLETED", r.error
        return deepcopy(r.result["candidates"][0]), r.live_calls


def test_tracking_failure_switches_clips_and_completes_in_six_calls(store, fallback):
    c, calls = completed(store, fallback)
    assert calls == 6 and c["clip"]["id"] == fallback.second["id"]
    assert fallback.tracked == [fallback.first["id"], fallback.second["id"]]
    assert fallback.operations == ["verify_clips", "critic", "critic", "decide"]
    assert [t["outcome"] for t in c["clip_attempts"]] == ["tracking_unclear", "usable"]
    assert c["clip_fallback"]["tried_alternative"] and c["tracking_accepted"]
    assert c["metrics"][0]["value"] is not None
    with session_scope(store) as s:
        logs = list(
            s.scalars(
                select(PerceptionLog)
                .where(PerceptionLog.scan_id == fallback.sid)
                .order_by(PerceptionLog.attempt)
            )
        )
        assert [l.data["clip_id"] for l in logs] == [fallback.first["id"], fallback.second["id"]]
        assert len(list(s.scalars(select(ModelCall).where(ModelCall.scan_id == fallback.sid)))) == 6


def test_unconfirmed_identity_can_show_anonymous_scene_tracks_without_named_metrics(
    store, fallback
):
    fallback.scene_only = True
    c, calls = completed(store, fallback)
    assert calls == 6
    assert c["verified"] is False and c["tracking_accepted"] is False
    assert c["tracking_review"]["scene_only"] is True
    assert {o["role"] for f in c["reviewed_tracking"]["frames"] for o in f["objects"]} == {
        "unknown",
        "ball",
    }
    assert all(m["value"] is None for m in c["metrics"])


def test_unclear_identity_uses_other_prechecked_clip_without_tracking_rejected_player(
    store, fallback
):
    fallback.identity_bad = True
    fallback.bad_first = False
    c, calls = completed(store, fallback)
    assert calls == 4 and c["clip"]["id"] == fallback.second["id"]
    assert fallback.tracked == [fallback.second["id"]]
    assert c["clip_attempts"][0]["outcome"] == "identity_unclear"


def test_clear_first_clip_does_not_run_another_tracking_pass(store, fallback):
    fallback.bad_first = False
    c, calls = completed(store, fallback)
    assert calls == 4 and fallback.tracked == [fallback.first["id"]]
    assert len(c["clip_attempts"]) == 1 and c["clip_fallback"]["stop_reason"] == "usable_clip"


def test_two_unclear_clips_finish_report_without_inventing_metrics(store, fallback):
    fallback.both_bad = True
    c, calls = completed(store, fallback)
    assert calls == 6 and c["clip_fallback"]["stop_reason"] == "no_clear_clip"
    assert len(c["clip_attempts"]) == 2 and all(m["value"] is None for m in c["metrics"])
    assert "none provided clear" in c["clip_fallback"]["notice"]


def test_budget_is_reserved_for_report_instead_of_starting_partial_second_analysis(
    store, fallback, monkeypatch
):
    monkeypatch.setattr(settings, "max_live_model_calls_per_scan", 5)
    c, calls = completed(store, fallback)
    assert calls == 4 and fallback.tracked == [fallback.first["id"]]
    assert c["clip_fallback"]["stop_reason"] == "budget_limit"


def test_no_supported_measurements_switches_even_with_good_tracking_score(store, fallback):
    fallback.bad_first = False
    fallback.no_observations = True
    c, calls = completed(store, fallback)
    assert calls == 6 and c["clip"]["id"] == fallback.second["id"]
    assert c["clip_attempts"][0]["outcome"] == "no_usable_metrics"


@pytest.mark.parametrize("duplicate", ["absent", "hash", "source"])
def test_missing_or_repeated_footage_is_not_analyzed_as_a_new_clip(store, fallback, duplicate):
    with session_scope(store) as s:
        second = s.get(Clip, fallback.second["id"])
        if duplicate == "absent":
            s.delete(second)
        elif duplicate == "hash":
            second.content_hash = fallback.first["content_hash"]
            second.data = {**second.data, "content_hash": fallback.first["content_hash"]}
        else:
            first = s.get(Clip, fallback.first["id"])
            for row in [first, second]:
                row.data = {**row.data, "source_ref": "https://example.test/same-original"}
    c, calls = completed(store, fallback)
    assert calls == 4 and len(fallback.tracked) == 1
    assert c["clip_fallback"]["stop_reason"] == "no_alternative"


def test_checkpoint_resume_keeps_first_trial_and_the_accumulated_call_count(
    store, fallback, monkeypatch
):
    original = scan.Job.save
    crash = [True]

    def save(job):
        original(job)
        if crash[0] and any(len(t) == 1 for t in job.cp.get("clip_trials", {}).values()):
            crash[0] = False
            raise RuntimeError("OFFLINE crash after durable first trial")

    monkeypatch.setattr(scan.Job, "save", save)
    assert scan.run_once(store)
    with session_scope(store) as s:
        r = s.get(ScanRun, fallback.sid)
        assert r.stage == "FAILED" and r.live_calls == 3
        r.stage = "QUEUED"
        r.lease_until = 0
    monkeypatch.setattr(scan.Job, "save", original)
    c, calls = completed(store, fallback)
    assert calls == 6 and c["clip"]["id"] == fallback.second["id"]
    assert fallback.tracked == [fallback.first["id"], fallback.second["id"]]
    assert fallback.operations.count("verify_clips") == 1


def test_resume_after_final_decision_does_not_spend_another_call(store, fallback, monkeypatch):
    original = scan.Job.save
    crash = [True]

    def save(job):
        original(job)
        if crash[0] and "decision" in job.cp:
            crash[0] = False
            raise RuntimeError("OFFLINE crash after persisted decision")

    monkeypatch.setattr(scan.Job, "save", save)
    assert scan.run_once(store)
    with session_scope(store) as s:
        r = s.get(ScanRun, fallback.sid)
        assert r.stage == "FAILED" and r.live_calls == 6
        r.stage = "QUEUED"
        r.lease_until = 0
    monkeypatch.setattr(scan.Job, "save", original)
    c, calls = completed(store, fallback)
    assert calls == 6 and fallback.operations.count("decide") == 1
    assert c["clip"]["id"] == fallback.second["id"]


@pytest.mark.parametrize("failure", ["transport_failure", "invalid_batch"])
def test_provider_errors_do_not_trigger_automatic_paid_retries(store, fallback, failure):
    setattr(fallback, failure, True)
    assert scan.run_once(store)
    with session_scope(store) as s:
        r = s.get(ScanRun, fallback.sid)
        assert r.stage == "FAILED" and r.live_calls <= 3
    assert len(fallback.tracked) <= 1 and fallback.operations.count("verify_clips") == 1


def test_public_import_stops_on_access_or_rate_limit_errors(store, monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr(settings, "public_footage_analysis_enabled", True)
    provider = AutomaticClipProvider(store)
    seen = []

    def denied(*args, **kwargs):
        seen.append(True)
        raise FootageError("OFFLINE HTTP 429", stop_source=True)

    monkeypatch.setattr(provider, "prepare_entry", denied)
    source = {
        "publisher": "ESPN",
        "_media_url": "https://espnmedia-cdn.akamaized.net/fixture.mp4",
        "url": "https://www.espn.com/video/clip/_/id/1",
        "game_date": str(datetime.now(timezone.utc).date()),
        "title": "OFFLINE fixture",
    }
    with pytest.raises(FootageError, match="429"):
        provider.import_public(
            {"id": "c1", "nba_id": "123"},
            [source, {**source, "url": "https://www.espn.com/video/clip/_/id/2"}],
        )
    assert seen == [True]
