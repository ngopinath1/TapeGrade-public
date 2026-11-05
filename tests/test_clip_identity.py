"""Synthetic evidence checks; no identity is inferred from the test images."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from PIL import Image

from backend.api.types import ClipVerification
from backend.config import settings
from backend.services.clip_identity import (
    assess_identity,
    game_identity_context,
    jersey,
    review_tracking_identity,
)
from backend.services.clips import media_url, local_path


def source_context():
    def athlete(aid, name, number):
        return {"athlete": {"id": aid, "displayName": name, "jersey": number}, "didNotPlay": False}

    summary = {
        "boxscore": {
            "players": [
                {
                    "team": {"abbreviation": "BOS"},
                    "statistics": [
                        {
                            "athletes": [
                                athlete("1", "Sam Hauser", "30"),
                                athlete("2", "Teammate", "11"),
                            ]
                        }
                    ],
                },
                {
                    "team": {"abbreviation": "ORL"},
                    "statistics": [{"athletes": [athlete("3", "Opponent", "22")]}],
                },
            ]
        }
    }
    player = {"id": "fixture-player", "name": "Sam Hauser", "team": "BOS"}
    return player, summary


@pytest.fixture
def identity_inputs(store):
    player, summary = source_context()
    frames = []
    for frame in [0, 10]:
        path = settings.data_dir / "cache" / f"synthetic-identity-{frame}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (100, 100), "#444444").save(path)
        frames.append({"frame": frame, "time": frame / 10, "url": media_url(path)})
    clip = {
        "content_hash": "synthetic-identity-fixture",
        "width": 100,
        "height": 100,
        "frames": frames,
        "game_date": "2026-11-01",
        "source_identity": game_identity_context(summary, "123", "2026-11-01", player),
    }
    reply = {
        "verified": True,
        "confidence": 0.9,
        "reason": "Synthetic visual contract",
        "target_description": "white jersey 30",
        "objects": [
            {
                "id": 1,
                "role": "target",
                "box": [10, 10, 25, 80],
                "team_code": "BOS",
                "jersey_number": "30",
                "jersey_readable": True,
            },
            {
                "id": 2,
                "role": "defender",
                "box": [50, 10, 70, 80],
                "team_code": "ORL",
                "jersey_number": "22",
                "jersey_readable": True,
            },
        ],
        "identity_observations": [
            {
                "frame": i,
                "jersey_number": "30",
                "team_code": "BOS",
                "legibility": "clear",
                "box": [10, 10, 25, 80],
                "evidence": "Synthetic jersey reading",
            }
            for i in [0, 10]
        ],
        "continuity_frames": [0, 10],
    }
    return player, clip, reply


def test_roster_jersey_and_track_bindings_are_separate_and_auditable(identity_inputs):
    p, c, v = identity_inputs
    out = assess_identity(p, c, ClipVerification.model_validate(v))
    assert out["status"] == "corroborated" and out["expected_jersey"] == "30"
    assert out["tracked_players"][0]["name"] == "Sam Hauser"
    assert out["tracked_players"][1]["name"] == "Opponent"
    assert all(local_path(e["crop_url"]).is_file() for e in out["evidence"])


@pytest.mark.parametrize(
    "fault",
    [
        "no_roster",
        "unclear",
        "wrong_number",
        "different_seed",
        "one_frame",
        "teammate_defender",
        "duplicate_id",
        "unseen_frame",
        "seed_number_conflict",
        "out_of_bounds",
    ],
)
def test_identity_abstains_on_missing_or_conflicting_evidence(identity_inputs, fault):
    p, c, v = deepcopy(identity_inputs)
    if fault == "no_roster":
        c["source_identity"] = {}
    elif fault == "unclear":
        v["identity_observations"][0]["legibility"] = "unclear"
    elif fault == "wrong_number":
        v["identity_observations"][1]["jersey_number"] = "31"
    elif fault == "different_seed":
        v["objects"][0]["box"] = [70, 10, 90, 80]
    elif fault == "one_frame":
        v["continuity_frames"] = [0]
    elif fault == "teammate_defender":
        v["objects"][1]["team_code"] = "BOS"
    elif fault == "duplicate_id":
        v["objects"][1]["id"] = 1
    elif fault == "unseen_frame":
        v["identity_observations"][0]["frame"] = 1234
    elif fault == "seed_number_conflict":
        v["objects"][0]["jersey_number"] = "11"
    elif fault == "out_of_bounds":
        v["objects"][1]["box"] = [50, 10, 150, 80]
    out = assess_identity(p, c, ClipVerification.model_validate(v))
    assert out["status"] == "unconfirmed" and out["reasons"]
    assert all(x["name"] is None for x in out["tracked_players"])


def test_unreadable_opponents_remain_unnamed(identity_inputs):
    p, c, v = identity_inputs
    v["objects"][1].update(jersey_readable=False, jersey_number=None)
    out = assess_identity(p, c, ClipVerification.model_validate(v))
    assert out["status"] == "corroborated"
    assert out["tracked_players"][1]["name"] is None


def test_clear_later_seed_can_confirm_target_without_a_frame_zero_jersey(identity_inputs):
    p, c, v = deepcopy(identity_inputs)
    v["objects"][0]["frame"] = 10
    v["identity_observations"][0]["legibility"] = "unclear"
    out = assess_identity(p, c, ClipVerification.model_validate(v))
    assert out["status"] == "corroborated"
    assert out["evidence"][0]["frame"] == 10


def test_context_does_not_bind_a_jersey_to_two_roster_players():
    p, summary = source_context()
    row = summary["boxscore"]["players"][0]["statistics"][0]["athletes"][1]["athlete"]
    row["jersey"] = "30"
    assert not game_identity_context(summary, "123", "2026-11-01", p)["roster_match"]


def test_jersey_zero_and_double_zero_remain_distinct():
    assert jersey(0) == "0"
    assert jersey("00") == "00"


@pytest.mark.parametrize(
    "target,teams,conflicts",
    [
        (None, True, []),
        (True, None, []),
        (False, True, []),
        (True, False, []),
        (True, True, ["teammate used as defender"]),
    ],
)
def test_tracking_identity_requires_explicit_target_and_team_confirmation(target, teams, conflicts):
    identity = {"status": "corroborated", "reasons": []}
    critique = SimpleNamespace(
        target_identity_preserved=target, team_roles_preserved=teams, role_conflicts=conflicts
    )
    assert not review_tracking_identity(identity, critique)
    assert identity["status"] == "tracking_rejected"
    # Repeated checks retain one reason, and a supported correction can recover.
    assert not review_tracking_identity(identity, critique)
    assert len(identity["reasons"]) == 1
    corrected = SimpleNamespace(
        target_identity_preserved=True, team_roles_preserved=True, role_conflicts=[]
    )
    assert review_tracking_identity(identity, corrected)
    assert identity == {"status": "corroborated", "reasons": []}


def test_tracking_cannot_upgrade_an_unconfirmed_seed():
    identity = {"status": "unconfirmed", "reasons": ["No readable jersey"]}
    critique = SimpleNamespace(
        target_identity_preserved=True, team_roles_preserved=True, role_conflicts=[]
    )
    assert not review_tracking_identity(identity, critique)
    assert identity["status"] == "unconfirmed"


def test_specific_failed_target_check_overrides_a_positive_general_check():
    identity = {"status": "corroborated", "reasons": []}
    critique = SimpleNamespace(
        target_identity_preserved=True,
        team_roles_preserved=True,
        role_conflicts=[],
        player_identity_checks=[SimpleNamespace(object_id=1, identity_preserved=False)],
    )
    assert not review_tracking_identity(identity, critique)
    assert identity["status"] == "tracking_rejected"
