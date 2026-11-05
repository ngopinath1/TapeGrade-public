"""HTTP end-to-end test; requires the separate API, frontend and worker to be running.

Refuses to run with live models, so it cannot spend Meta credits.
"""

import time

import httpx


def main():
    with httpx.Client(base_url="http://127.0.0.1:5173", timeout=20) as client:
        health = client.get("/api/health")
        health.raise_for_status()
        assert health.json()["models"] == "mock", "Smoke test is mock-only; no scan created."
        assert client.get("/").status_code == 200
        response = client.post("/api/scans", json={"instruction": "Find me an undervalued guard."})
        response.raise_for_status()
        sid = response.json()["id"]
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            detail = client.get("/api/scans/" + sid)
            detail.raise_for_status()
            run = detail.json()
            if run["stage"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.5)
        assert run["stage"] == "COMPLETED", run.get("error") or "Worker did not finish in 90s"
        result = run["result"]
        assert result["simulated"] and result["staged_move"]
        assert result["staged_move"]["guardrails_checked"]
        assert result["staged_move"]["executed"] is False
        assert run["live_calls"] == 0
        for c in result["candidates"]:
            measured = {
                m["name"] for m in c["metrics"] if m["value"] is not None and m["evidence_frames"]
            }
            assert set(c["verdict"]["metric_refs"]) <= measured
        assert any("Retrying tracking" in e["message"] for e in run["events"])
        card = client.get(f"/api/scans/{sid}/card")
        card.raise_for_status()
        assert card.content.startswith(b"\x89PNG")
        clip = result["candidates"][0]["clip"]
        video = client.get(clip["url"], headers={"Range": "bytes=0-255"})
        assert video.status_code in (200, 206)
        print(
            f'PASS scan={sid} candidates={len(result["candidates"])} card_bytes={len(card.content)} live_calls=0'
        )


if __name__ == "__main__":
    main()
