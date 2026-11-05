from backend.services.sample import ensure_sample


def test_permitted_upload_is_normalized_and_persisted(client, store):
    path = ensure_sample("c6")
    response = client.post(
        "/api/clips",
        data={"player_id": "c6", "rights_confirmed": "true"},
        files={"file": ("permitted.mp4", path.read_bytes(), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    clip = response.json()
    assert not clip["is_demo"] and clip["width"] == 960 and clip["height"] == 540
    assert clip["fps"] == 12 and 0 < clip["duration"] <= 30
    assert len(clip["frames"]) == 5
    assert client.get("/api/clips").json()[0]["id"] == clip["id"]
    assert client.get(clip["url"]).status_code == 200
