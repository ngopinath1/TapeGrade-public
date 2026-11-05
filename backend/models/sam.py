from hashlib import sha256
from pathlib import Path

from meta_sam_parser import (
    CompletedOutcome,
    FramePrompt,
    PromptBox,
    PromptObject,
    build_object_prompt,
    decode_mask_to_raster,
    video_segmentation_format,
)
from PIL import Image

from backend.api.types import Tracking
from backend.config import settings
from backend.models.base import ModelError
from backend.models.transport import MetaTransport, data_url
from backend.services.clips import media_url


def seed_prompt(
    clip: dict, objects: list[dict], frame: int | None = None, *, require_target=True
) -> str:
    ids = set()
    for obj in objects:
        anchor = frame if frame is not None else obj.get("frame", 0)
        sampled = {f["frame"] for f in clip.get("frames", [])}
        if not 0 <= anchor < clip["duration"] * clip["fps"] or (sampled and anchor not in sampled):
            raise ModelError("Spatial seed frame must be an inspected frame inside the clip.")
        x1, y1, x2, y2 = obj["box"]
        if obj["id"] in ids or not (0 <= x1 < x2 < clip["width"] and 0 <= y1 < y2 < clip["height"]):
            raise ModelError("Muse Spark returned invalid or duplicate source-pixel seed boxes.")
        ids.add(obj["id"])
    if require_target and len([o for o in objects if o["role"] == "target"]) != 1:
        raise ModelError("Spatial guidance requires exactly one verified target.")
    if not objects:
        raise ModelError("Spatial guidance requires at least one visible object.")
    return build_object_prompt(
        size=(clip["width"], clip["height"]),
        objects=[
            PromptObject(
                id=o["id"],
                prompts=[
                    FramePrompt(
                        frame=frame if frame is not None else o.get("frame", 0),
                        box=PromptBox(o["box"][0], o["box"][1], o["box"][2] + 1, o["box"][3] + 1),
                    )
                ],
            )
            for o in objects
        ],
    )


def corrected_prompt(clip, original_objects, critique):
    """Use reviewed spatial corrections without losing defender/ball role IDs."""
    if critique.retry_objects:
        objects = [o.model_dump() for o in critique.retry_objects]
        before = {o["id"]: o["role"] for o in original_objects}
        after = {o["id"]: o["role"] for o in objects}
        sampled = {f["frame"] for f in clip["frames"]}
        if before != after or critique.retry_frame not in sampled:
            raise ModelError(
                "Spatial correction must preserve verified role bindings and reference an inspected frame."
            )
        return seed_prompt(
            clip,
            objects,
            critique.retry_frame,
            require_target=any(o["role"] == "target" for o in original_objects),
        )
    # Free-form concept ordinals cannot retain multiple spatial role bindings.
    if len(original_objects) > 1 and not critique.refined_prompt.strip().startswith("<"):
        return None
    return critique.refined_prompt.strip() or None


def parse_tracking(
    raw: str, clip: dict, prompt: str, objects: list[dict], directory: Path | None = None
) -> Tracking:
    parser = video_segmentation_format().create_parser()
    parser.push(raw)
    parsed = parser.finish(CompletedOutcome()).result
    if parsed.diagnostics:
        raise ModelError("SAM output contains malformed geometry; partial tracking was rejected.")
    # Rechecks may produce different masks for the same prompt; retain older report assets.
    key = sha256((clip["content_hash"] + settings.sam_model + prompt + raw).encode()).hexdigest()
    directory = directory or settings.data_dir / "cache" / "sam" / key
    directory.mkdir(parents=True, exist_ok=True)
    raw_path = directory / "response.txt"
    raw_path.write_text(raw)
    boxes = [r for r in parsed.records if r.kind == "box"]
    masks = {
        (r.frame.frame_index if r.frame else 0, r.object_id): r
        for r in parsed.records
        if r.kind == "mask"
    }
    # Concept prompts provide ordinals, not the spatial seed IDs. Assign a target
    # only for a single matched concept; never relabel other matches as defenders.
    spatial = prompt.startswith("<")
    roles = {str(o["id"]): o["role"] for o in objects} if spatial else {}
    concept_ids = {b.object_id for b in boxes}
    frames = {}
    for box in boxes:
        frame = box.frame.frame_index if box.frame else 0
        if frame / clip["fps"] > clip["duration"] or not (
            0 <= box.left < box.right <= clip["width"]
            and 0 <= box.top < box.bottom <= clip["height"]
        ):
            raise ModelError("SAM returned geometry outside the source media bounds.")
        record = masks.get((frame, box.object_id))
        if record is None:
            raise ModelError("SAM box is missing its mask.")
        try:
            raster = list(decode_mask_to_raster(record.mask))
            if not any(raster):
                continue
            mask = Image.frombytes(
                "L", (record.mask.width, record.mask.height), bytes(255 if b else 0 for b in raster)
            )
        except Exception:
            raise ModelError(
                "SAM mask payload could not be decoded by the official parser."
            ) from None
        path = directory / f"{frame}-{box.object_id}.png"
        mask.save(path)
        role = (
            roles.get(box.object_id, "unknown")
            if spatial
            else "target" if len(concept_ids) == 1 else "unknown"
        )
        frames.setdefault(frame, []).append(
            {
                "id": int(box.object_id),
                "role": role,
                "box": [box.left, box.top, box.right - 1, box.bottom - 1],
                "centroid": [(box.left + box.right - 1) / 2, (box.top + box.bottom - 1) / 2],
                "mask_url": media_url(path),
                "mask_polygon": None,
            }
        )
    return Tracking(
        width=clip["width"],
        height=clip["height"],
        fps=clip["fps"],
        prompt=prompt,
        simulated=False,
        raw_path=media_url(raw_path),
        frames=[
            {"frame": f, "time": f / clip["fps"], "objects": o} for f, o in sorted(frames.items())
        ],
    )


class SAMClient:
    def __init__(self, transport=None):
        self.transport = transport or MetaTransport()

    def track(self, clip, prompt, objects):
        if clip["is_demo"]:
            raise ModelError(
                "Live SAM does not automatically process simulated sample footage. Upload permitted video."
            )
        raw = self.transport.stream_text(
            {
                "model": settings.sam_model,
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {
                                "type": "input_video",
                                "video_url": data_url(clip["url"], "video/mp4"),
                            },
                        ],
                    }
                ],
                "stream": True,
                "metadata": {"mask_encoding": "one_bit"},
            }
        )
        return parse_tracking(raw, clip, prompt, objects)
