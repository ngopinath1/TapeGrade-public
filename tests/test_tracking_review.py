"""Offline geometry and per-object review contracts; no inference or identity guesses."""

from copy import deepcopy

import pytest

from backend.api.types import ClipVerification, Criticism, Tracking
from backend.models.base import ModelError
from backend.models.sam import seed_prompt
from backend.services.metrics import calculate_metrics
from backend.services.tracking_review import reviewed_tracking, tracking_seeds


def inputs():
    clip = {
        "width": 960,
        "height": 540,
        "fps": 12,
        "duration": 5,
        "public_source": True,
        "frames": [{"frame": f} for f in (0, 12, 24, 36, 48)],
        "source_identity": {
            "expected_player": {"team": "BOS"},
            "roster": [{"team": "BOS"}, {"team": "ORL"}],
        },
    }
    objects = [
        {"id": 1, "role": "target", "frame": 12, "box": [100, 100, 150, 250], "team_code": "BOS"},
        {"id": 2, "role": "defender", "frame": 0, "box": [250, 100, 300, 250], "team_code": "ORL"},
        {"id": 15, "role": "ball", "frame": 24, "box": [140, 150, 152, 162]},
    ]
    verification = ClipVerification(
        verified=True,
        confidence=0.95,
        reason="Synthetic fixture",
        target_description="fixture",
        objects=objects,
    )
    tracking = Tracking(
        width=960,
        height=540,
        fps=12,
        prompt="<spatial>",
        simulated=False,
        frames=[
            {
                "frame": f,
                "time": f / 12,
                "objects": [
                    {
                        "id": o["id"],
                        "role": o["role"],
                        "box": o["box"],
                        "centroid": [
                            (o["box"][0] + o["box"][2]) / 2,
                            (o["box"][1] + o["box"][3]) / 2,
                        ],
                    }
                    for o in objects
                ],
            }
            for f in range(60)
        ],
    )
    checks = [
        {
            "object_id": o["id"],
            "quality_score": 0.92,
            "identity_preserved": True,
            "role_correct": True,
            "reason": "Synthetic visible object",
        }
        for o in objects
    ]
    critique = Criticism(
        quality_score=0.4,
        identity_swaps=[],
        missing_tracking=[],
        incorrect_masks=[],
        occlusion_problems=[],
        retry_justified=False,
        refined_prompt="",
        explanation="Synthetic independent checks",
        object_tracking_checks=checks,
    )
    return clip, verification, tracking, critique


def test_each_object_can_start_in_a_different_inspected_frame():
    clip, verification, _, _ = inputs()
    seeds = tracking_seeds(clip, verification, True)
    prompt = seed_prompt(clip, seeds)
    assert "<12f>" in prompt and "<24f>" in prompt and "<0f>" in prompt
    seeds[-1]["frame"] = 23
    with pytest.raises(ModelError, match="inspected"):
        seed_prompt(clip, seeds)


def test_uncertain_identity_keeps_people_anonymous_and_ball_separate():
    clip, verification, tracking, critique = inputs()
    seeds = tracking_seeds(clip, verification, False)
    assert [s["role"] for s in seeds] == ["unknown", "unknown", "ball"]
    seed_prompt(clip, seeds, require_target=False)
    reviewed, summary = reviewed_tracking(tracking, seeds, critique, False, 0.1)
    assert summary["scene_only"] and summary["target_quality"] == 0
    assert summary["roles"] == {"target": 0, "defender": 0, "ball": 1, "unknown": 2}
    assert all(m.value is None for m in calculate_metrics(reviewed, 0))


def test_teammate_and_duplicate_target_are_never_defenders():
    clip, verification, _, _ = inputs()
    verification.objects[1].team_code = "BOS"
    assert tracking_seeds(clip, verification, True)[1]["role"] == "unknown"
    verification.objects[1].frame = 12
    verification.objects[1].box = list(verification.objects[0].box)
    assert 2 not in {s["id"] for s in tracking_seeds(clip, verification, True)}


def test_failed_defender_and_ball_do_not_hide_a_confirmed_target():
    clip, verification, tracking, critique = inputs()
    for check in critique.object_tracking_checks[1:]:
        check.identity_preserved = False
        check.quality_score = 0.2
        check.reason = "Track moved onto empty court or a hand"
    reviewed, summary = reviewed_tracking(
        tracking, tracking_seeds(clip, verification, True), critique, True, 0.95
    )
    assert summary["target_quality"] == 0.92
    assert summary["roles"] == {"target": 1, "defender": 0, "ball": 0, "unknown": 0}
    assert {o.id for f in reviewed.frames for o in f.objects} == {1}
    assert all(m.value is None for m in calculate_metrics(reviewed, 0.92))


def test_lost_object_is_not_drawn_after_its_reviewed_failure_frame():
    clip, verification, tracking, critique = inputs()
    check = critique.object_tracking_checks[1]
    check.identity_preserved = False
    check.unreliable_from_frame = 24
    reviewed, summary = reviewed_tracking(
        tracking,
        tracking_seeds(clip, verification, True),
        critique,
        True,
        0.95,
        {f["frame"] for f in clip["frames"]},
    )
    assert all(o.id != 2 for f in reviewed.frames if f.frame >= 24 for o in f.objects)
    assert any(o.id == 2 for f in reviewed.frames if f.frame < 24 for o in f.objects)
    check.unreliable_from_frame = 25
    reviewed, _ = reviewed_tracking(
        tracking,
        tracking_seeds(clip, verification, True),
        critique,
        True,
        0.95,
        {f["frame"] for f in clip["frames"]},
    )
    assert all(o.id != 2 for f in reviewed.frames for o in f.objects)


def test_empty_tracking_cannot_get_a_positive_target_score():
    clip, verification, tracking, critique = inputs()
    tracking.frames = []
    _, summary = reviewed_tracking(
        tracking, tracking_seeds(clip, verification, True), critique, True, 0.95
    )
    assert summary["target_quality"] == 0 and summary["trusted_object_ids"] == []


def test_overlay_never_borrows_boxes_from_a_different_source_frame(store):
    from PIL import Image
    from backend.config import settings
    from backend.services.clips import media_url, local_path
    from backend.services.overlays import create_overlays

    source = settings.data_dir / "cache" / "source.jpg"
    source.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 100), "black").save(source)
    clip = {
        "frames": [
            {"frame": 0, "time": 0, "url": media_url(source)},
            {"frame": 12, "time": 1, "url": media_url(source)},
        ]
    }
    tracking = Tracking(
        width=100,
        height=100,
        fps=12,
        prompt="<12f>",
        simulated=False,
        frames=[
            {
                "frame": 12,
                "time": 1,
                "objects": [
                    {"id": 1, "role": "target", "box": [10, 10, 40, 70], "centroid": [25, 40]}
                ],
            }
        ],
    )
    urls = create_overlays(clip, tracking, "frame-alignment-test")
    with Image.open(local_path(urls[0])) as before, Image.open(local_path(urls[1])) as actual:
        assert max(before.getpixel((10, 30))) < 10
        assert max(actual.getpixel((10, 30))) > 80
