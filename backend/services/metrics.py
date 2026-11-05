from math import dist
from statistics import mean

from backend.api.types import Metric, Tracking


def calculate_metrics(tracking: Tracking, quality: float) -> list[Metric]:
    distances, involved, evidence, ball_evidence = [], [], [], []
    for frame in tracking.frames:
        targets = [o for o in frame.objects if o.role == "target"]
        defenders = [o for o in frame.objects if o.role == "defender"]
        balls = [o for o in frame.objects if o.role == "ball"]
        if len(targets) != 1:
            continue
        target = targets[0]
        if defenders:
            distances.append(min(dist(target.centroid, d.centroid) for d in defenders))
            evidence.append(frame.frame)
        if len(balls) == 1:
            # Threshold scales with the observed target box, not court calibration.
            body_height = max(1, target.box[3] - target.box[1])
            involved.append(dist(target.centroid, balls[0].centroid) <= body_height * 0.8)
            ball_evidence.append(frame.frame)
    enough = len(evidence) >= 4 and quality >= 0.6
    enough_ball = len(ball_evidence) >= 4 and quality >= 0.6
    coverage = len(ball_evidence) / max(1, len(tracking.frames))
    return [
        Metric(
            name="defender_proximity",
            label="Nearest defender",
            value=round(mean(distances), 1) if enough else None,
            unit="px",
            confidence=min(quality, 0.8) if enough else 0,
            description="Mean screen-space distance between target and nearest identified defender box centroids. Camera perspective affects this proxy; pixels are not feet.",
            evidence_frames=evidence if enough else [],
            unavailable_reason=(
                None
                if enough
                else "Fewer than four reliable target/defender observations or low perception quality."
            ),
        ),
        Metric(
            name="on_ball_involvement",
            label="On-ball involvement",
            value=round(mean(involved) * 100, 1) if enough_ball else None,
            unit="%",
            confidence=min(quality, 0.78) * coverage if enough_ball else 0,
            description="Percent of jointly observed target/ball frames within 0.8 target-box heights. Ball proximity proxy, not possession or official usage.",
            evidence_frames=ball_evidence if enough_ball else [],
            unavailable_reason=(
                None
                if enough_ball
                else "Ball and target not jointly tracked reliably in at least four frames."
            ),
        ),
        Metric(
            name="shot_opportunity",
            label="Shot opportunity",
            value=None,
            unit="",
            confidence=0,
            description="Requires reliable rim localization, camera calibration and action evidence.",
            evidence_frames=[],
            unavailable_reason="Not measured in v1; centroid proximity cannot establish a shot.",
        ),
        Metric(
            name="defensive_activity",
            label="Defensive activity",
            value=None,
            unit="",
            confidence=0,
            description="Requires possession context and camera-motion compensation.",
            evidence_frames=[],
            unavailable_reason="Not measured in v1; movement alone cannot establish a closeout.",
        ),
    ]
