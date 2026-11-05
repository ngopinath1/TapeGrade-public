"""Offline tests for the real-video diagnostic. All model responses are fixtures."""

import base64
from io import BytesIO
import json

import httpx
from PIL import Image
from pydantic import SecretStr
import pytest

from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import CalculatedMetric, ModelCall, ScanRun, StagedMove
from backend.models.base import ModelError
from backend.services.sample import ensure_sample
from backend.worker.film import enqueue_film, retry_film
from backend.worker.scan import Job, run_once
from scripts.film_check import prepare
from tests.test_models import WIRE


@pytest.mark.parametrize(
    "quality,verified,truncate",
    [(0.9, True, False), (0.4, True, False), (0.9, False, False), (0.9, True, True)],
)
def test_diagnostic_real_clients_bounded_calls_persistence_and_no_fantasy_move(
    store, client, monkeypatch, quality, verified, truncate
):
    player, clip = prepare(
        ensure_sample("c1"),
        1,
        4,
        "Fixture #4",
        "Cream jersey #4; offline test subject.",
        "FIX",
        4,
        store,
    )
    assert clip["duration"] == 4
    assert clip["provenance"]["excerpt_start"] == 1
    assert player["fantasy_points"] is None and player["stats"] == {}
    assert clip["is_demo"] is False and player["film_only"] is True
    with pytest.raises(ModelError, match="MOCK_MODELS=0"):
        enqueue_film(player, clip, store)
    monkeypatch.setattr(settings, "mock_models", False)
    monkeypatch.setattr(settings, "model_api_key", SecretStr("offline-test-key"))
    image = BytesIO()
    Image.new("RGB", (64, 64), "#182015").save(image, format="PNG")
    requests = []
    critic_calls = 0

    def handler(request):
        nonlocal critic_calls
        requests.append(request.url.path)
        payload = json.loads(request.content)
        if request.url.path == "/v1/images/generations":
            return httpx.Response(
                200, json={"data": [{"b64_json": base64.b64encode(image.getvalue()).decode()}]}
            )
        if request.url.path == "/v1/responses":
            target = WIRE.replace("w=320;h=334", "w=960;h=540").replace(">0<|box", ">1<|box")
            defender = (
                target.replace(">1<|box", ">2<|box")
                .replace("x1=211", "x1=300")
                .replace("x2=270", "x2=359")
            )
            ball = target.replace(">1<|box", ">15<|box")
            line = target + "," + defender.split("<0f>")[1] + "," + ball.split("<0f>")[1]
            text = "\n".join(line.replace("<0f>", f"<{f}f>") for f in [0, 6, 12, 18, 24])
            events = [
                {"type": "response.output_text.delta", "delta": text},
                {"type": "response.completed"},
            ]
            return httpx.Response(
                200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events)
            )
        content = json.loads(payload["messages"][1]["content"][0]["text"])
        if content["operation"] == "verify":
            out = {
                "verified": verified,
                "confidence": 0.95,
                "reason": "Offline fixture only.",
                "target_description": "cream jersey",
                "objects": [
                    {"id": 1, "role": "target", "box": [211, 228, 270, 254]},
                    {"id": 2, "role": "defender", "box": [300, 228, 359, 254]},
                    {"id": 15, "role": "ball", "box": [230, 230, 241, 241]},
                ],
            }
        else:
            assert content["operation"] == "critic"
            critic_calls += 1
            if truncate and critic_calls == 1:
                return httpx.Response(
                    200,
                    json={"choices": [{"finish_reason": "length", "message": {"content": "{"}}]},
                )
            out = {
                "quality_score": quality,
                "identity_swaps": [],
                "missing_tracking": [],
                "incorrect_masks": [],
                "occlusion_problems": [],
                "retry_justified": quality < 0.75,
                "refined_prompt": "cream jersey player",
                "explanation": "Offline tracking assessment fixture.",
            }
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(out)}}]},
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    sid = enqueue_film(player, clip, store)
    assert run_once(store)
    if truncate:
        with session_scope(store) as s:
            failed = s.get(ScanRun, sid)
            assert failed.stage == "FAILED" and failed.live_calls == 3
            assert failed.result["candidates"][0]["tracking"] is not None
        assert not run_once(store)  # no automatic paid retry
        response = client.post(f"/api/scans/{sid}/retry")
        assert response.status_code == 202
        assert run_once(store)
    with session_scope(store) as s:
        row = s.get(ScanRun, sid)
        assert row.stage == "COMPLETED", row.error
        assert row.live_calls == (5 if truncate else 4 if verified else 1)
        result = row.result
        candidate = result["candidates"][0]
        assert result["film_test"] and not result["simulated"]
        assert candidate["player"]["fantasy_points"] is None
        assert result["staged_move"] is None and s.query(StagedMove).count() == 0
        assert s.query(ModelCall).filter_by(scan_id=sid).count() == row.live_calls
        if verified:
            assert not candidate["tracking"]["simulated"]
            assert len(candidate["tracking"]["frames"]) == 5
            assert requests.count("/v1/responses") == 1  # no retry, even on low quality
            assert result["card"]["simulated"] is False
            assert s.query(CalculatedMetric).filter_by(scan_id=sid).count() == 4
            assert (candidate["metrics"][0]["value"] is not None) == (quality >= 0.6)
            job = Job(sid, row.worker_token, store)
        else:
            assert result["card"] is None
            assert candidate["tracking"] is None
    assert enqueue_film(player, clip, store) == sid
    assert not run_once(store)
    if verified:
        monkeypatch.setattr(settings, "max_live_model_calls_per_scan", 50)
        with pytest.raises(ModelError, match="budget"):
            job.reserve_call("fixture", "fifth-call-blocked")
    with pytest.raises(ModelError, match="failed film diagnostic"):
        retry_film(sid, factory=store)


@pytest.mark.parametrize("start,duration", [(-1, 4), (0, 6), (float("nan"), 4), (7, 4)])
def test_excerpt_bounds_are_enforced_locally_without_inference(store, start, duration):
    with pytest.raises(ValueError, match="excerpt"):
        prepare(ensure_sample("c1"), start, duration, "Fixture", "Offline fixture", factory=store)
