"""Real client/control-loop code with in-memory HTTP fixtures, NEVER paid inference."""

import base64
from io import BytesIO
import json

import httpx
from PIL import Image
from pydantic import SecretStr

from backend.api.types import Criticism, Decision, Shortlist
from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import ScanRun
from backend.models.mock import MockSpark
from backend.services.clips import prepare_clip
from backend.services.sample import ensure_sample
from backend.worker.scan import enqueue, run_once
from tests.test_models import WIRE


def test_live_pipeline_all_three_clients_and_critic_changes_next_sam_request(store, monkeypatch):
    monkeypatch.setattr(settings, "mock_models", False)
    monkeypatch.setattr(settings, "model_api_key", SecretStr("offline-test-key"))
    monkeypatch.setattr(settings, "max_candidates", 1)
    prepare_clip(ensure_sample("c1"), "c1", False, store)
    image_bytes = BytesIO()
    Image.new("RGB", (256, 256), "#203018").save(image_bytes, format="PNG")
    requests = []
    boxes = [
        {"id": 0, "role": "target", "box": [211, 228, 270, 254]},
        {"id": 1, "role": "defender", "box": [300, 228, 359, 254]},
        {"id": 2, "role": "ball", "box": [230, 230, 241, 241]},
    ]

    def handler(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path == "/v1/images/generations":
            return httpx.Response(
                200,
                json={"data": [{"b64_json": base64.b64encode(image_bytes.getvalue()).decode()}]},
            )
        if request.url.path == "/v1/responses":
            line = WIRE.replace("w=320;h=334", "w=960;h=540")
            defender = (
                line.replace(">0<|box", ">1<|box")
                .replace("x1=211", "x1=300")
                .replace("x2=270", "x2=359")
            )
            ball = (
                line.replace(">0<|box", ">2<|box")
                .replace("x1=211", "x1=230")
                .replace("x2=270", "x2=241")
                .replace("y1=228", "y1=230")
                .replace("y2=254", "y2=241")
            )
            combined = line + "," + defender.split("<0f>")[1] + "," + ball.split("<0f>")[1]
            text = "\n".join(combined.replace("<0f>", f"<{f}f>") for f in [0, 6, 12, 18, 24])
            events = [
                {"type": "response.output_text.delta", "delta": text},
                {"type": "response.completed", "response": {}},
            ]
            return httpx.Response(
                200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events)
            )
        data = json.loads(payload["messages"][1]["content"][0]["text"])
        op, evidence = data["operation"], data["evidence"]
        if op == "verify":
            out = {
                "verified": True,
                "confidence": 0.95,
                "reason": "OFFLINE contract fixture only",
                "target_description": "cream jersey",
                "objects": boxes,
            }
        elif op == "critic":
            failed = evidence["attempt"] == 0
            out = {
                "quality_score": 0.4 if failed else 0.9,
                "identity_swaps": ["offline fixture swap"] if failed else [],
                "missing_tracking": [],
                "incorrect_masks": [],
                "occlusion_problems": [],
                "retry_justified": failed,
                "refined_prompt": "<6f>0<|box;x1=211;y1=228;x2=270;y2=254;w=960;h=540|>,1<|box;x1=300;y1=228;x2=359;y2=254;w=960;h=540|>,2<|box;x1=230;y1=230;x2=241;y2=241;w=960;h=540|>",
                "explanation": "Offline fixture correction; not a live model result.",
            }
        else:
            out = (
                MockSpark()
                .reason(op, evidence, Shortlist if op == "scout" else Decision)
                .model_dump()
            )
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
    sid = enqueue("Find a guard", factory=store)
    assert run_once(store)
    with session_scope(store) as s:
        row = s.get(ScanRun, sid)
        assert row.stage == "COMPLETED", row.error
        assert row.result["card"]["simulated"] is False
        assert row.result["candidates"][0]["tracking"]["simulated"] is False
        assert row.result["staged_move"] is not None
        assert row.live_calls == 8
    sam = [p for path, p in requests if path == "/v1/responses"]
    assert len(sam) == 2
    assert sam[0]["input"][0]["content"][0]["text"].startswith("<0f>")
    assert sam[1]["input"][0]["content"][0]["text"].startswith("<6f>")
    assert {p["model"] for _, p in requests} == {"muse-spark-1.3", "sam-3.1", "muse-image-1.0"}
