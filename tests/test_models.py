import base64
import json

import httpx
import pytest
from pydantic import SecretStr

from backend.api.types import Shortlist
from backend.config import settings
from backend.models.base import ModelError
from backend.models.muse_image import MuseImage
from backend.models.muse_spark import MuseSpark
from backend.models.sam import SAMClient, parse_tracking, seed_prompt
from backend.models.transport import MetaTransport
from backend.worker.scan import Job, claim, enqueue

# Small, documented wire-format example from Meta's SAM grammar documentation.
WIRE = "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>"


def live_transport(monkeypatch, handler):
    monkeypatch.setattr(settings, "mock_models", False)
    monkeypatch.setattr(settings, "model_api_key", SecretStr("offline-test-key"))
    return MetaTransport(httpx.Client(transport=httpx.MockTransport(handler)))


def test_spark_documented_request_and_schema_validation(monkeypatch):
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        assert req.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "player_ids": ["c1"],
                                    "roster_need": "guard",
                                    "reasoning": "evidence",
                                }
                            )
                        },
                    }
                ]
            },
        )

    spark = MuseSpark(live_transport(monkeypatch, handler))
    result = spark.reason("scout", {"instruction": "Find guard"}, Shortlist)
    assert result.player_ids == ["c1"]
    assert seen[0]["model"] == "muse-spark-1.3"
    assert seen[0]["response_format"]["json_schema"]["schema"] == Shortlist.model_json_schema()


def test_spark_rejects_bad_output(monkeypatch):
    spark = MuseSpark(
        live_transport(
            monkeypatch,
            lambda r: httpx.Response(
                200, json={"choices": [{"message": {"content": '{"player_ids": ["x"]}'}}]}
            ),
        )
    )
    with pytest.raises(ModelError, match="schema"):
        spark.reason("scout", {}, Shortlist)


def test_sam_masks_boxes_and_explicit_frame_order(store):
    clip = {"width": 320, "height": 334, "fps": 12, "duration": 2, "content_hash": "fixture"}
    raw = WIRE.replace("<0f>", "<6f>") + "\n" + WIRE
    result = parse_tracking(raw, clip, "button", [])
    assert [f.frame for f in result.frames] == [0, 6]
    assert result.frames[0].objects[0].box == [211, 228, 270, 254]
    assert result.frames[1].time == 0.5
    from backend.services.clips import local_path
    from PIL import Image

    mask = Image.open(local_path(result.frames[0].objects[0].mask_url))
    assert mask.size == (60, 27) and mask.getextrema()[1] == 255
    assert result.simulated is False


def test_zero_sam_matches_is_valid_and_has_no_metrics(store):
    from backend.services.metrics import calculate_metrics

    clip = {"width": 320, "height": 334, "fps": 12, "duration": 2, "content_hash": "empty-fixture"}
    result = parse_tracking("", clip, "absent jersey", [])
    assert result.frames == []
    assert all(m.value is None for m in calculate_metrics(result, 0))


def test_sam_stream_request_and_refined_prompt(monkeypatch, store):
    seen = []
    video = settings.data_dir / "uploads" / "sample.mp4"
    video.parent.mkdir(exist_ok=True)
    video.write_bytes(b"contract-test-video")

    def handler(req):
        seen.append(json.loads(req.content))
        events = [
            {"type": "response.output_text.delta", "delta": WIRE},
            {"type": "response.completed", "response": {}},
        ]
        return httpx.Response(
            200,
            text="".join("data: " + json.dumps(e) + "\n\n" for e in events),
            headers={"Content-Type": "text/event-stream"},
        )

    sam = SAMClient(live_transport(monkeypatch, handler))
    clip = {
        "width": 320,
        "height": 334,
        "fps": 12,
        "duration": 2,
        "content_hash": "fixture",
        "url": "/media/uploads/sample.mp4",
        "is_demo": False,
    }
    objects = [{"id": 0, "role": "target", "box": [211, 228, 270, 254]}]
    initial = seed_prompt(clip, objects)
    result = sam.track(clip, initial, objects)
    refined = "<6f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|>"
    sam.track(clip, refined, objects)
    assert seen[0]["input"][0]["content"][0]["text"] == initial
    assert seen[1]["input"][0]["content"][0]["text"] == refined
    assert seen[0]["metadata"]["mask_encoding"] == "one_bit"
    assert seen[0]["input"][0]["content"][1]["video_url"].startswith("data:video/mp4;base64,")
    assert result.frames[0].objects[0].role == "target"


def test_incomplete_stream_rejected(monkeypatch):
    transport = live_transport(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            text="data: "
            + json.dumps({"type": "response.output_text.delta", "delta": WIRE})
            + "\n\n",
        ),
    )
    with pytest.raises(ModelError, match="without response.completed"):
        transport.stream_text({"model": "sam-3.1"})


def test_image_documented_endpoint_and_bytes(monkeypatch):
    class JobStub:
        def cached(self, m, o, p, call):
            return call()

    def handler(req):
        data = json.loads(req.content)
        assert req.url.path == "/v1/images/generations"
        assert data["model"] == "muse-image-1.0" and data["n"] == 1
        return httpx.Response(
            200, json={"data": [{"b64_json": base64.b64encode(b"PNG-contract-fixture").decode()}]}
        )

    image = MuseImage(JobStub(), live_transport(monkeypatch, handler))
    assert image.generate("court art") == b"PNG-contract-fixture"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
def test_model_errors_are_sanitized(monkeypatch, status):
    t = live_transport(
        monkeypatch,
        lambda r: httpx.Response(status, json={"error": "offline-test-key and internal details"}),
    )
    with pytest.raises(ModelError) as err:
        t.post("/chat/completions", {})
    assert str(status) in str(err.value) and "offline-test-key" not in str(err.value)


def test_mock_and_live_cache_separation_and_budget(store, monkeypatch):
    sid = enqueue("Find guard", factory=store)
    claimed = claim(store)
    job = Job(*claimed, store)
    assert job.cached("model", "op", {}, lambda: {"value": "mock"}) == {"value": "mock"}
    job.mode = "live"
    monkeypatch.setattr(settings, "max_live_model_calls_per_scan", 1)
    assert job.cached("model", "op", {}, lambda: {"value": "live"}) == {"value": "live"}
    # Cache hits do not spend calls; a distinct input respects the persisted cap.
    assert job.cached("model", "op", {}, lambda: None) == {"value": "live"}
    with pytest.raises(ModelError, match="budget"):
        job.cached("model", "op", {"new": 1}, lambda: {})


def test_real_transport_disabled_in_mock_mode():
    with pytest.raises(ModelError):
        MetaTransport()
