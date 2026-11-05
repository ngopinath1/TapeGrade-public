"""The local-use boundary applies before API handlers and static media."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("path", ["/api/bootstrap", "/docs", "/media/cache/private.json"])
def test_remote_clients_cannot_read_workspace_or_media(client, path):
    from backend.main import app

    with TestClient(app, base_url="http://localhost:8000", client=("192.0.2.10", 50000)) as remote:
        assert remote.get(path).status_code == 403


def test_remote_client_cannot_queue_paid_work(client):
    from backend.main import app

    with TestClient(app, base_url="http://localhost:8000", client=("192.0.2.10", 50000)) as remote:
        assert remote.post("/api/scans", json={"instruction": "Find a guard"}).status_code == 403
    assert client.get("/api/scans").json() == []


@pytest.mark.parametrize(
    "host", ["attacker.example", "localhost.attacker.example", "localhost@attacker.example"]
)
def test_rebinding_host_is_rejected(client, host):
    assert client.get("/api/bootstrap", headers={"Host": host}).status_code == 403


@pytest.mark.parametrize("origin", ["https://attacker.example", "null", "http://localhost:9999"])
def test_untrusted_origin_cannot_change_workspace(client, origin):
    response = client.post("/api/workspace/demo", headers={"Origin": origin})
    assert response.status_code == 403


def test_cross_site_form_without_origin_is_rejected(client):
    assert (
        client.post("/api/workspace/demo", headers={"Sec-Fetch-Site": "cross-site"}).status_code
        == 403
    )


def test_local_frontend_and_api_docs_still_work(client):
    response = client.get("/api/bootstrap", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert client.get("/docs").status_code == 200
    response = client.options(
        "/api/settings",
        headers={"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "PUT"},
    )
    assert response.status_code == 200


def test_ipv6_loopback_is_supported(client):
    from backend.main import app

    with TestClient(app, base_url="http://[::1]:8000", client=("::1", 50000)) as ipv6:
        assert ipv6.get("/api/health").status_code == 200
