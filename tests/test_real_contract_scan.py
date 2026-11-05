"""Synthetic real-league contract path. No production readiness bypass exists.

This test FIRST asserts synthetic data is blocked. It then patches only its local
get_league result to exercise actual HTTP clients and staging on synthetic inputs.
It is not a live model accuracy test and never consumes external API credits.
"""

import base64
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import shutil

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select

from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import Clip, ModelCall, ScanRun
from backend.models.base import ModelError
from backend.services.clips import prepare_clip, local_path
from backend.services.sample import ensure_sample
from backend.services.state import get_league
from backend.worker import scan
from tests.test_models import WIRE
from tests.test_statistics import connect_batch
from tests.test_live_staging import inputs


@pytest.mark.parametrize("reviewed_eligibility", [True, False])
@pytest.mark.parametrize("automatic", [True, False])
def test_real_league_contract_all_clients_budget_and_export(
    client, store, monkeypatch, reviewed_eligibility, automatic
):
    connect_batch(store)
    assert get_league(store)["scouting_ready"] is False
    blocked = client.post("/api/scans", json={"instruction": "Inspect one candidate"})
    assert blocked.status_code == 409
    # Explicit test-only override: fixtures must never qualify production readiness.
    unit_context, _, decision = inputs()
    league = deepcopy(get_league(store))
    league["scouting_ready"] = True
    league["fetched_at"] = unit_context["fetched_at"]
    league["eligibility_reviews"] = (
        unit_context["eligibility_reviews"] if reviewed_eligibility else {}
    )
    for p in league["roster"] + league["available"]:
        p["recent"]["ready"] = True  # test-only; retain synthetic labels and actual fixture rows
    player = league["available"][0]
    player.update(name="SYNTHETIC CONTRACT CANDIDATE", number=4)
    player["recent"].update(synthetic=True, sample_size=5)
    league["stats_summary"] = {
        "provider": "offline_contract_fixture",
        "synthetic": True,
        "source_ref": "offline:synthetic-contract",
    }
    monkeypatch.setattr(scan, "get_league", lambda factory=None, league_id=None: deepcopy(league))
    monkeypatch.setattr(settings, "mock_models", False)
    monkeypatch.setattr(settings, "model_api_key", SecretStr("offline-test-key"))
    monkeypatch.setattr(settings, "max_candidates", 1)
    monkeypatch.setattr(settings, "max_sam_retries", 1)
    monkeypatch.setattr(settings, "max_live_model_calls_per_scan", 8)
    if automatic:
        # Only the fixture's source adapters are replaced. The preparation,
        # checkpoints, real model clients and final gates all run normally.
        from backend.services import scan_workflow

        monkeypatch.setattr(settings, "nba_stats_provider", "sportradar")
        monkeypatch.setattr(settings, "sportradar_api_key", SecretStr("offline-statistics-key"))
        monkeypatch.setattr(scan_workflow, "get_league", lambda *a: deepcopy(league))
        monkeypatch.setattr(scan_workflow, "refresh_roster", lambda *a: None)
        monkeypatch.setattr(scan_workflow, "statistics_fresh", lambda *a: True)
    clip = prepare_clip(ensure_sample("c1"), player["id"], False, store)
    with session_scope(store) as s:
        row = s.get(Clip, clip["id"])
        row.data = {**row.data, "source": "OFFLINE original procedural schematic, no real athlete"}
    png = BytesIO()
    Image.new("RGB", (256, 256), "#203018").save(png, format="PNG")
    requests = []
    objects = [
        {"id": 0, "role": "target", "box": [211, 228, 270, 254]},
        {"id": 1, "role": "defender", "box": [300, 228, 359, 254]},
        {"id": 2, "role": "ball", "box": [230, 230, 241, 241]},
    ]

    def handler(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path == "/v1/images/generations":
            return httpx.Response(
                200, json={"data": [{"b64_json": base64.b64encode(png.getvalue()).decode()}]}
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
        op, e = data["operation"], data["evidence"]
        if op == "scout":
            out = {
                "player_ids": [player["id"]],
                "roster_need": "OFFLINE fixture",
                "reasoning": "Synthetic fixture candidate only.",
            }
        elif op == "verify":
            out = {
                "verified": True,
                "confidence": 0.95,
                "reason": "OFFLINE schematic fixture only",
                "target_description": "cream jersey",
                "objects": objects,
            }
        elif op == "critic":
            failed = e["attempt"] == 0
            out = {
                "quality_score": 0.4 if failed else 0.9,
                "identity_swaps": [],
                "missing_tracking": [],
                "incorrect_masks": ["Synthetic defender drift"] if failed else [],
                "occlusion_problems": [],
                "retry_justified": failed,
                "refined_prompt": "",
                "explanation": "OFFLINE fixture correction only.",
                "retry_objects": objects if failed else [],
                "retry_frame": clip["frames"][1]["frame"] if failed else 0,
            }
        else:
            out = decision.model_dump()
            out["verdicts"][0]["metric_refs"] = ["on_ball_involvement"]
            out["verdicts"][0][
                "rationale"
            ] = "OFFLINE synthetic contract: metrics, nullable bid and source checks exercised."
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(out)}}]},
        )

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    sid = scan.enqueue(
        "OFFLINE synthetic one-candidate contract test", factory=store, prepare=automatic
    )
    assert scan.run_once(store)
    with session_scope(store) as s:
        row = s.get(ScanRun, sid)
        assert row.stage == "COMPLETED", row.error
        assert row.checkpoint.get("preparation_done", False) == automatic
        assert row.live_calls == 8 and row.checkpoint["live_call_limit"] == 8
        assert row.result["league_is_demo"] is False
        assert row.result["candidates"][0]["tracking_accepted"] is True
        if reviewed_eligibility:
            assert row.result["staged_move"]["faab_bid"] is None
            assert row.result["staged_move"]["executed"] is False
        else:
            assert row.result["staged_move"] is None
            assert row.result["candidates"][0]["verdict"]["verdict"] == "MONITOR"
            assert row.result["scan_notice"].startswith("Scouting report only")
        assert row.checkpoint["league"]["stats_summary"]["synthetic"] is True
        assert len(row.checkpoint["league"]["roster"][0]["recent"]["games"]) == 5
        assert len(row.result["candidates"][0]["player"]["recent"]["games"]) == 5
        assert row.result["card"]["visual_source"] == "Offline HTTP contract fixture artwork"
    sam = [p for path, p in requests if path == "/v1/responses"]
    assert len(sam) == 2
    assert sam[0]["input"][0]["content"][0]["text"].startswith("<0f>")
    assert sam[1]["input"][0]["content"][0]["text"].startswith(f"<{clip['frames'][1]['frame']}f>")
    assert {p["model"] for _, p in requests} == {"muse-spark-1.3", "sam-3.1", "muse-image-1.0"}
    card = client.get(f"/api/scans/{sid}/card")
    assert card.status_code == 200 and card.content[:8] == b"\x89PNG\r\n\x1a\n"
    evidence = client.get(f"/api/scans/{sid}/evidence")
    assert evidence.status_code == 200
    assert len(evidence.json()["model_calls"]) == 8
    output = os.environ.get("TAPEGRADE_CONTRACT_ARTIFACT_DIR")
    if output and reviewed_eligibility:
        folder = Path(output)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "tapegrade-offline-contract.png").write_bytes(card.content)
        report = evidence.json()
        report["execution"] = {
            "offline": True,
            "synthetic": True,
            "paid_requests": 0,
            "fixture_http_calls": 8,
            "budget": 8,
            "external_transactions": 0,
        }

        def media_refs(value):
            if isinstance(value, str) and value.startswith("/media/"):
                yield value
            elif isinstance(value, dict):
                for child in value.values():
                    yield from media_refs(child)
            elif isinstance(value, list):
                for child in value:
                    yield from media_refs(child)

        report["evidence_assets"] = {}
        for ref in set(media_refs(report)):
            original_path = local_path(ref)
            if original_path.is_file():
                relative = Path("assets") / ref.removeprefix("/media/")
                target = folder / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original_path, target)
                report["evidence_assets"][ref] = str(relative)
        (folder / "evidence.json").write_text(json.dumps(report, indent=2))
        import zipfile

        with zipfile.ZipFile(
            folder / "tapegrade-offline-contract.zip", "w", zipfile.ZIP_DEFLATED
        ) as bundle:
            for name in [
                "tapegrade-offline-contract.png",
                "evidence.json",
                *report["evidence_assets"].values(),
            ]:
                bundle.write(folder / name, name)
