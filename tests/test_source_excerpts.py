"""Non-overlapping source ranges are views of one play, never new games."""

from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from backend.config import settings
from backend.providers.footage import ESPNFootageDiscovery
from backend.services.clips import overlapping_source, source_key, source_span
from backend.worker.clip_scan import clip_plan, trial_summary


@pytest.mark.parametrize(
    "last_source", ["https://example.test/other", "https://example.test/highlight"]
)
def test_overlapping_alternative_does_not_hide_a_later_distinct_clip(monkeypatch, last_source):
    monkeypatch.setattr(settings, "max_clips_per_candidate", 2)

    def clip(cid, start, end, ref="https://example.test/highlight"):
        return {
            "id": cid,
            "content_hash": cid,
            "source_ref": ref,
            "source_span": {"start": start, "end": end},
        }

    available = [clip("first", 0, 5), clip("overlap", 3, 8), clip("next", 11, 16, last_source)]
    calls = []

    class Provider:
        def find(self, player, ids, hashes, refs):
            calls.append(True)
            return next((c for c in available if c["id"] not in ids), None)

    job = SimpleNamespace(
        cp={"max_clips_per_candidate": 2}, event=lambda *a, **k: None, save=lambda: None
    )
    plan = clip_plan(job, {"id": "fixture", "name": "Fixture Player"}, False, Provider(), None, 12)
    assert [c["id"] for c in plan["clips"]] == ["first", "next"]
    assert len(calls) == 3


def test_rejected_clip_explains_the_actual_visual_reason():
    candidate = {
        "clip": {"id": "source"},
        "verified": False,
        "quality": 0,
        "verification": {
            "verified": False,
            "confidence": 0.35,
            "reason": "The opening frame has no readable number 30.",
        },
        "identity": {"reasons": ["Internal seed-box requirement not met"]},
    }
    assert trial_summary(candidate, 1, False)["reason"] == candidate["verification"]["reason"]


@pytest.mark.parametrize(
    "span,overlaps",
    [
        (None, True),
        ({"start": 0, "end": 5}, True),
        ({"start": 4, "end": 9}, True),
        ({"start": 5, "end": 10}, False),
        ({"start": 11, "end": 16}, False),
        ({"start": True, "end": 10}, True),
        ({"start": float("nan"), "end": 10}, True),
    ],
)
def test_only_explicit_nonoverlapping_ranges_are_distinct(span, overlaps):
    first = {"source_ref": "https://example.test/highlight", "source_span": {"start": 0, "end": 5}}
    second = {"source_ref": first["source_ref"], "source_span": span}
    assert overlapping_source(first, second) is overlaps
    if not overlaps:
        assert source_key(first) != source_key(second)


@pytest.mark.parametrize(
    "length,include_media,count", [(16, True, 2), (9, True, 1), (16, False, 1)]
)
def test_discovery_adds_later_excerpt_only_when_long_enough(
    store, monkeypatch, length, include_media, count
):
    monkeypatch.setattr(settings, "max_clip_seconds", 5)
    day = datetime.now(timezone.utc).date().isoformat()

    def handler(request):
        if "/schedule" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "events": [
                        {
                            "id": "123",
                            "date": day + "T18:00Z",
                            "competitions": [{"status": {"type": {"completed": True}}}],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "videos": [
                    {
                        "id": 456,
                        "headline": "Sam Hauser drills a three",
                        "description": "Sam Hauser scores",
                        "duration": length,
                        "source": "espn",
                        "links": {
                            "source": {"href": "https://espnmedia-cdn.akamaized.net/fixture.mp4"}
                        },
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        sources = ESPNFootageDiscovery(c).find({"name": "Sam Hauser", "team": "BOS"}, include_media)
    assert len(sources) == count
    if count == 2:
        assert sources[0]["url"] == sources[1]["url"]
        assert sources[1]["_start_seconds"] == 11 and sources[1]["_duration_seconds"] == 5
        assert sources[1]["excerpt_of_same_highlight"] is True
        assert sources[1]["_identity_context"] == sources[0]["_identity_context"]
