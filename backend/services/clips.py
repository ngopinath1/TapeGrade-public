import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Protocol
from urllib.parse import urldefrag

from sqlalchemy import select

from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import Clip
from backend.services.sample import ensure_sample


class ClipProvider(Protocol):
    def find(self, player_id: str) -> dict | None: ...


def source_span(data):
    span = data.get("source_span") or {}
    start, end = span.get("start"), span.get("end")
    if (
        type(start) in (int, float)
        and type(end) in (int, float)
        and math.isfinite(start)
        and math.isfinite(end)
        and 0 <= start < end
    ):
        return (float(start), float(end))
    return None


def source_key(data):
    ref = data.get("source_ref")
    if not ref:
        return None
    ref = urldefrag(ref)[0]
    span = source_span(data)
    return f"{ref}|excerpt:{span[0]:g}:{span[1]:g}" if span else ref


def overlapping_source(a, b):
    if (
        not a.get("source_ref")
        or not b.get("source_ref")
        or urldefrag(a["source_ref"])[0] != urldefrag(b["source_ref"])[0]
    ):
        return False
    left, right = source_span(a), source_span(b)
    return not left or not right or max(left[0], right[0]) < min(left[1], right[1])


def media_url(path: Path) -> str:
    return "/media/" + str(path.relative_to(settings.data_dir))


def inspect_video(path: Path, max_input_seconds: float = 600) -> dict:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate,codec_name:format=duration,format_name",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=20,
        )
        raw = json.loads(result.stdout)
        if not {"mov", "mp4"} & set(raw["format"]["format_name"].split(",")):
            raise ValueError("The file must contain an actual MP4 or MOV container.")
        v = raw["streams"][0]
        duration = float(raw["format"]["duration"])
        n, d = map(float, v["r_frame_rate"].split("/"))
        if (
            not 0 < duration <= max_input_seconds
            or not 0 < n / d <= 240
            or not 0 < v["width"] <= 7680
            or not 0 < v["height"] <= 4320
        ):
            raise ValueError(
                f"Unsupported video dimensions, frame rate, or duration (max {max_input_seconds:g} seconds input)."
            )
        return {
            "width": v["width"],
            "height": v["height"],
            "fps": n / d,
            "duration": duration,
            "codec": v["codec_name"],
        }
    except (
        subprocess.SubprocessError,
        KeyError,
        IndexError,
        ZeroDivisionError,
        json.JSONDecodeError,
    ) as e:
        raise ValueError(
            "Invalid or unreadable video. Upload MP4 or MOV with a video stream."
        ) from e


def prepare_clip(path: Path, player_id: str, is_demo: bool, factory=None) -> dict:
    meta = inspect_video(path)
    if meta["duration"] > settings.max_clip_seconds + 0.1:
        raise ValueError("Processed clip exceeds the configured analysis duration.")
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    with session_scope(factory) as s:
        existing = s.scalar(
            select(Clip).where(
                Clip.content_hash == content_hash,
                Clip.player_id == player_id,
                Clip.is_demo == is_demo,
            )
        )
        if existing:
            return existing.data
    directory = settings.data_dir / "cache" / "frames" / content_hash
    directory.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, fraction in enumerate([0, 0.2, 0.4, 0.6, 0.8]):
        time = min(meta["duration"] - 0.05, meta["duration"] * fraction)
        source_frame = round(time * meta["fps"])
        time = source_frame / meta["fps"]
        frame_path = directory / f"{i}.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(path),
                "-vf",
                f"select=eq(n\\,{source_frame})",
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(frame_path),
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )
        frames.append({"time": time, "frame": source_frame, "url": media_url(frame_path)})
    with session_scope(factory) as s:
        clip = Clip(player_id=player_id, content_hash=content_hash, is_demo=is_demo, data={})
        s.add(clip)
        s.flush()
        clip.data = {
            "id": clip.id,
            "player_id": player_id,
            "content_hash": content_hash,
            "url": media_url(path),
            "is_demo": is_demo,
            "frames": frames,
            **meta,
            "source": (
                "Original procedural schematic"
                if is_demo
                else "User upload · processing rights confirmed"
            ),
        }
        return clip.data


class LocalClipProvider:
    def __init__(self, mock: bool, factory=None):
        self.mock, self.factory = mock, factory

    def find(
        self, player_id: str, excluded_ids=(), excluded_hashes=(), excluded_sources=()
    ) -> dict | None:
        with session_scope(self.factory) as s:
            clips = s.scalars(
                select(Clip)
                .where(Clip.player_id == player_id, Clip.is_demo == False)
                .order_by(Clip.created_at.desc())
            )
            for clip in clips:
                if (
                    clip.id not in excluded_ids
                    and clip.content_hash not in excluded_hashes
                    and source_key(clip.data) not in excluded_sources
                    and clip.data.get("source_ref") not in excluded_sources
                    and usable_upload(clip.data)
                ):
                    return clip.data
        if self.mock and not excluded_ids and not excluded_hashes:
            return prepare_clip(ensure_sample(player_id), player_id, True, self.factory)
        return None


def usable_upload(data: dict) -> bool:
    try:
        if data.get("automatically_matched"):
            from datetime import date, datetime, timezone

            age = (datetime.now(timezone.utc).date() - date.fromisoformat(data["game_date"])).days
            if not 0 <= age <= settings.footage_max_age_days:
                return False
        return (
            local_path(data["url"]).is_file()
            and 0 < data["duration"] <= settings.max_clip_seconds + 0.1
        )
    except (KeyError, ValueError, TypeError):
        return False


def players_with_permitted_clips(league: dict, factory=None) -> list[dict]:
    """Select only existing uploads before spending live scouting credits."""
    with session_scope(factory) as s:
        uploads = s.scalars(select(Clip).where(Clip.is_demo == False)).all()
        ready = {clip.player_id for clip in uploads if usable_upload(clip.data)}
    return [p for p in league["available"] if p["id"] in ready]


def local_path(url: str) -> Path:
    if not url.startswith("/media/"):
        raise ValueError("Only local media references can be processed.")
    path = (settings.data_dir / url.removeprefix("/media/")).resolve()
    if not path.is_relative_to(settings.data_dir.resolve()):
        raise ValueError("Invalid media path")
    return path
