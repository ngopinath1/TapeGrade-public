import re

from backend.api.types import Tracking
from backend.services.sample import FPS, HEIGHT, SECONDS, WIDTH, scene


class MockSpark:
    def reason(self, operation, payload, schema, images=None):
        if operation == "scout":
            instruction = payload["instruction"].lower()
            positions = (
                {"PG", "SG"}
                if re.search(r"guard|\bpg\b|\bsg\b", instruction)
                else (
                    {"C"}
                    if re.search(r"center|\bc\b", instruction)
                    else (
                        {"C", "PF"}
                        if re.search(r"big|rebound", instruction)
                        else {"SF", "PF"} if re.search(r"wing|forward", instruction) else set()
                    )
                )
            )
            ranked = sorted(
                payload["available"],
                key=lambda p: (
                    bool(positions & set(p["positions"])),
                    p["minutes"] - p["previous_minutes"],
                    p["fantasy_points"],
                ),
                reverse=True,
            )
            ids = [p["id"] for p in ranked if not positions or positions & set(p["positions"])][
                : payload["limit"]
            ]
            result = dict(
                player_ids=ids,
                roster_need=(
                    "Backcourt opportunity"
                    if positions == {"PG", "SG"}
                    else "Best available role growth"
                ),
                reasoning="Simulated scout ranks position fit, minute growth and sample fantasy production.",
            )
        elif operation == "verify":
            demo = payload["clip"]["is_demo"]
            result = dict(
                verified=demo,
                confidence=1 if demo else 0,
                reason=(
                    "Original schematic explicitly represents this fictional player."
                    if demo
                    else "Mock models cannot verify identities in uploaded footage. Enable live models."
                ),
                target_description="cream basketball jersey",
                objects=(
                    [
                        {"id": o["id"], "role": o["role"], "box": [int(x) for x in o["box"]]}
                        for o in scene(payload["player"]["id"], 0)
                    ]
                    if demo
                    else []
                ),
            )
        elif operation == "critic":
            bad = payload["attempt"] == 0 and payload["player_id"] == "c1"
            result = dict(
                quality_score=0.46 if bad else 0.91,
                identity_swaps=["Target switches to defender at frame 48."] if bad else [],
                missing_tracking=[],
                incorrect_masks=[],
                occlusion_problems=(
                    ["Crossing bodies require a narrower identity cue."] if bad else []
                ),
                retry_justified=bad,
                refined_prompt="cream basketball jersey number 4" if bad else payload["prompt"],
                explanation=(
                    "Simulated identity swap detected. Refine the jersey attribute and rerun segmentation."
                    if bad
                    else "Simulated target identity and mask alignment accepted across sampled frames."
                ),
            )
        elif operation == "decide":
            verdicts = []
            for candidate in payload["candidates"]:
                metrics = {m["name"]: m for m in candidate["metrics"] if m["value"] is not None}
                onball = metrics.get("on_ball_involvement", {}).get("value", 0)
                quality = candidate["quality"]
                verdict = (
                    "ADD"
                    if quality >= 0.75 and onball >= 55
                    else "MONITOR" if quality >= 0.6 and onball >= 30 else "PASS"
                )
                confidence = min(
                    quality, 0.88 if verdict == "ADD" else 0.79 if verdict == "MONITOR" else 0.73
                )
                refs = list(metrics)
                rationale = (
                    f"Simulated film shows ball proximity in {onball:.0f}% of observed frames. "
                    if metrics
                    else "No reliable film metrics available. "
                )
                rationale += (
                    "Rising sample minutes support an opportunity-based add."
                    if verdict == "ADD"
                    else "Watch the role; current visual evidence does not justify an immediate add."
                )
                verdicts.append(
                    dict(
                        player_id=candidate["player"]["id"],
                        verdict=verdict,
                        confidence=confidence,
                        rationale=rationale,
                        strengths=(
                            ["Sample minutes are rising", "Film evidence stored by source frame"]
                            if metrics
                            else []
                        ),
                        weaknesses=[
                            "Small schematic sample; no real-game inference",
                            "Shot quality unavailable",
                        ],
                        metric_refs=refs,
                    )
                )
            adds = [v for v in verdicts if v["verdict"] == "ADD"]
            droppable = [
                p
                for p in payload["roster"]
                if p["id"] not in payload["guardrails"]["protected_players"]
            ]
            drop = min(droppable, key=lambda p: p["fantasy_points"]) if droppable else None
            move = (
                dict(
                    add_player_id=adds[0]["player_id"],
                    drop_player_id=drop["id"],
                    faab_bid=8,
                    reasoning=adds[0]["rationale"],
                )
                if adds and drop
                else None
            )
            result = dict(verdicts=verdicts, move=move)
        else:
            raise ValueError(f"Unknown mock operation: {operation}")
        return schema.model_validate(result)


class MockSAM:
    def track(self, clip, prompt, objects):
        frames = []
        for frame in range(0, FPS * SECONDS, 6):
            obs = scene(clip["player_id"], frame)
            if clip["player_id"] == "c1" and prompt == "cream basketball jersey" and frame >= 48:
                obs[0]["box"], obs[1]["box"] = obs[1]["box"], obs[0]["box"]
                obs[0]["centroid"], obs[1]["centroid"] = obs[1]["centroid"], obs[0]["centroid"]
                obs[0]["mask_polygon"], obs[1]["mask_polygon"] = (
                    obs[1]["mask_polygon"],
                    obs[0]["mask_polygon"],
                )
            frames.append({"frame": frame, "time": frame / FPS, "objects": obs})
        return Tracking(
            width=WIDTH, height=HEIGHT, fps=FPS, prompt=prompt, frames=frames, simulated=True
        )
