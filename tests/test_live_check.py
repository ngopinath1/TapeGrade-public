import json

import httpx
from pydantic import SecretStr

from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import ScanRun
from scripts.live_check import check


def test_catalog_check_makes_no_inference_and_does_not_expose_key(monkeypatch):
    monkeypatch.setattr(settings, "model_api_key", SecretStr("offline-test-key"))
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(
            200, json={"data": [{"id": m} for m in ("muse-spark-1.3", "sam-3.1", "muse-image-1.0")]}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = check(client=client)
    assert seen == ["/v1/models"]
    assert report["inference_calls_attempted"] == 0
    assert all(report["model_access"].values())
    assert "offline-test-key" not in json.dumps(report)


def test_explicit_spark_check_uses_one_bounded_real_client_request(monkeypatch):
    monkeypatch.setattr(settings, "model_api_key", SecretStr("offline-test-key"))
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "muse-spark-1.3"}]})
        data = json.loads(request.content)
        assert data["max_completion_tokens"] == 512
        assert data["reasoning_effort"] == "minimal"
        assert data["response_format"]["type"] == "json_schema"
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
                                    "reasoning": "Fictional guard opportunity.",
                                }
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 200, "completion_tokens": 40, "total_tokens": 240},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = check(spark=True, client=client)
    assert report["spark_inference"] == "passed"
    assert report["inference_calls_attempted"] == 1
    assert report["usage"]["total_tokens"] == 240
    assert settings.mock_models is True
    assert seen == ["/v1/models", "/v1/chat/completions"]
    assert report["sam_inference"] == report["image_inference"] == "not_run"


def test_rejected_key_stops_before_inference_and_sanitizes_error(monkeypatch):
    monkeypatch.setattr(settings, "model_api_key", SecretStr("offline-test-key"))
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"error": {"message": "offline-test-key"}})
        )
    ) as client:
        report = check(spark=True, client=client)
    assert report["inference_calls_attempted"] == 0
    assert "401" in report["error"]
    assert "offline-test-key" not in json.dumps(report)


def test_live_route_without_upload_cannot_spend_credits(client, store, monkeypatch):
    monkeypatch.setattr(settings, "mock_models", False)
    monkeypatch.setattr(settings, "model_api_key", SecretStr("offline-test-key"))
    response = client.post("/api/scans", json={"instruction": "Find me a guard"})
    assert response.status_code == 409
    assert "Upload a permitted clip" in response.json()["detail"]
    assert client.get("/api/scans").json() == []


def test_live_scout_snapshot_only_includes_players_with_permitted_files(store, monkeypatch):
    from backend.services.clips import prepare_clip
    from backend.services.sample import ensure_sample
    from backend.worker.scan import enqueue

    prepare_clip(ensure_sample("c1"), "c1", False, store)
    monkeypatch.setattr(settings, "mock_models", False)
    sid = enqueue("Find me a guard", factory=store)
    with session_scope(store) as s:
        assert [p["id"] for p in s.get(ScanRun, sid).checkpoint["league"]["available"]] == ["c1"]
