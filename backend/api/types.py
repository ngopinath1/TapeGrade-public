from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Guardrails(StrictModel):
    min_confidence: float = Field(0.75, ge=0, le=1)
    max_faab_bid: int = Field(12, ge=0, le=1000)
    protected_players: list[str] = Field(default_factory=lambda: ["r1", "r2", "r3"])
    schedule_enabled: bool = False
    pre_waiver_hour: int | None = Field(None, ge=0, le=23)
    scoring_weights: (
        dict[
            Annotated[str, Field(min_length=1, max_length=64)],
            Annotated[float, Field(ge=-1000, le=1000, allow_inf_nan=False)],
        ]
        | None
    ) = Field(None, min_length=1, max_length=64)


class ScanRequest(StrictModel):
    instruction: str = Field("Find me an undervalued guard.", min_length=3, max_length=1000)
    league_id: str | None = Field(None, min_length=1, max_length=100)


class Shortlist(StrictModel):
    player_ids: list[str] = Field(min_length=0, max_length=6)
    roster_need: str
    reasoning: str


class SeedObject(StrictModel):
    id: int = Field(ge=0, le=15)
    role: Literal["target", "defender", "ball", "unknown"]
    frame: int = Field(
        0, ge=0, description="Inspected source frame in which this object is clearly visible."
    )
    box: list[int] = Field(
        min_length=4,
        max_length=4,
        description="Inclusive source-pixel x1,y1,x2,y2 in this object's frame; retry objects use retry_frame.",
    )
    team_code: str | None = None
    jersey_number: str | None = None
    jersey_readable: bool = False


class IdentityObservation(StrictModel):
    frame: int = Field(ge=0)
    jersey_number: str | None
    team_code: str | None
    legibility: Literal["clear", "unclear"]
    box: list[int] = Field(min_length=4, max_length=4)
    evidence: str


class ClipVerification(StrictModel):
    verified: bool
    confidence: float = Field(ge=0, le=1)
    reason: str
    target_description: str
    objects: list[SeedObject] = Field(default_factory=list, max_length=16)
    identity_observations: list[IdentityObservation] = Field(default_factory=list, max_length=5)
    continuity_frames: list[int] = Field(default_factory=list, max_length=5)


class ClipIdentityCheck(StrictModel):
    clip_id: str
    verification: ClipVerification


class ClipIdentityChecks(StrictModel):
    clips: list[ClipIdentityCheck] = Field(min_length=1, max_length=2)


class TrackIdentityCheck(StrictModel):
    object_id: int = Field(ge=1, le=14)
    identity_preserved: bool
    reason: str


class ObjectTrackingCheck(StrictModel):
    object_id: int = Field(ge=0, le=15)
    quality_score: float = Field(ge=0, le=1)
    identity_preserved: bool
    role_correct: bool
    unreliable_from_frame: int | None = Field(None, ge=0)
    reason: str


class Criticism(StrictModel):
    quality_score: float = Field(ge=0, le=1)
    identity_swaps: list[str]
    missing_tracking: list[str]
    incorrect_masks: list[str]
    occlusion_problems: list[str]
    retry_justified: bool
    refined_prompt: str
    explanation: str
    retry_objects: list[SeedObject] = Field(default_factory=list, max_length=16)
    retry_frame: int = Field(0, ge=0)
    target_identity_preserved: bool | None = None
    team_roles_preserved: bool | None = None
    role_conflicts: list[str] = Field(default_factory=list)
    player_identity_checks: list[TrackIdentityCheck] = Field(default_factory=list, max_length=14)
    object_tracking_checks: list[ObjectTrackingCheck] = Field(default_factory=list, max_length=16)


class TrackingObject(StrictModel):
    id: int
    role: Literal["target", "defender", "ball", "unknown"]
    box: list[float] = Field(min_length=4, max_length=4)
    centroid: list[float] = Field(min_length=2, max_length=2)
    mask_url: str | None = None
    mask_polygon: list[list[float]] | None = None


class TrackingFrame(StrictModel):
    frame: int = Field(ge=0)
    time: float = Field(ge=0)
    objects: list[TrackingObject]


class Tracking(StrictModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    prompt: str
    frames: list[TrackingFrame]
    simulated: bool
    raw_path: str | None = None


class Metric(StrictModel):
    name: str
    label: str
    value: float | None
    unit: str
    confidence: float = Field(ge=0, le=1)
    description: str
    evidence_frames: list[int]
    unavailable_reason: str | None = None


class PlayerVerdict(StrictModel):
    player_id: str
    verdict: Literal["ADD", "MONITOR", "PASS"]
    confidence: float = Field(ge=0, le=1)
    rationale: str
    strengths: list[str]
    weaknesses: list[str]
    metric_refs: list[str]


class ProposedMove(StrictModel):
    add_player_id: str
    drop_player_id: str
    faab_bid: int | None = Field(None, ge=0)
    reasoning: str


class Decision(StrictModel):
    verdicts: list[PlayerVerdict]
    move: ProposedMove | None
