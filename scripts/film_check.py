"""Prepare a short excerpt locally; --execute queues a four-call live diagnostic.

Only the normalized excerpt and sampled frames can reach Meta. The original
long input remains local. The separate worker runs the durable analysis job.
"""

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import subprocess

from backend.config import settings
from backend.db.database import initialize, session_scope
from backend.db.schema import Clip, Player
from backend.models.base import ModelError
from backend.services.clips import inspect_video, prepare_clip
from backend.services.state import seed_demo
from backend.worker.film import enqueue_film, retry_film


def prepare(
    source, start, duration, subject, description, team="Unknown", number=None, factory=None
):
    source = Path(source).resolve(strict=True)
    meta = inspect_video(source, max_input_seconds=3600)
    if (
        not all(math.isfinite(x) for x in (start, duration))
        or start < 0
        or not 1 <= duration <= min(5, settings.max_clip_seconds)
        or start + duration > meta["duration"]
    ):
        raise ValueError(
            "Select a valid 1–5 second excerpt within the source video and active clip limit."
        )
    fingerprint = sha256(
        f"{source}|{source.stat().st_size}|{source.stat().st_mtime_ns}|{start}|{duration}".encode()
    ).hexdigest()
    directory = settings.data_dir / "uploads"
    directory.mkdir(exist_ok=True, parents=True)
    path = directory / f"film-{fingerprint}.mp4"
    if not path.exists():
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                str(start),
                "-i",
                str(source),
                "-t",
                str(duration),
                "-vf",
                "scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2",
                "-r",
                "12",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
    player = {
        "id": "film-"
        + sha256(f"{subject}|{description}|{team}|{number}".encode()).hexdigest()[:16],
        "name": subject,
        "target_description": description,
        "team": team,
        "number": number,
        "positions": ["Video subject"],
        "minutes": None,
        "previous_minutes": None,
        "fantasy_points": None,
        "trend": [],
        "stats": {},
        "is_demo": False,
        "film_only": True,
        "source": "User-provided video. Visible jersey description only; real name, game date and fantasy statistics unverified.",
    }
    with session_scope(factory) as s:
        if not s.get(Player, player["id"]):
            s.add(Player(id=player["id"], league_id="demo-nba", is_demo=False, data=player))
    clip = prepare_clip(path, player["id"], False, factory)
    clip = {
        **clip,
        "source": "User-provided local highlight excerpt · analysis authorized by user",
        "subject_name": subject,
        "provenance": {
            "filename": source.name,
            "source_duration": meta["duration"],
            "excerpt_start": start,
            "excerpt_duration": duration,
            "license": "Not independently verified; no redistribution or current-season claim.",
            "audio_removed": True,
        },
    }
    with session_scope(factory) as s:
        s.get(Clip, clip["id"]).data = clip
    return player, clip


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip", type=Path)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--duration", type=float, default=4)
    parser.add_argument(
        "--subject", required=True, help="Visible team/jersey label; do not guess identity."
    )
    parser.add_argument("--description", required=True)
    parser.add_argument("--team", default="Unknown")
    parser.add_argument("--number", type=int)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Queue an actual four-call Meta diagnostic for the separate live worker.",
    )
    parser.add_argument(
        "--retry",
        action="store_true",
        help="Explicitly continue this FAILED diagnostic with at most two additional calls (six total maximum); requires --execute.",
    )
    args = parser.parse_args()
    try:
        if args.retry and not args.execute:
            raise ModelError("--retry requires --execute; no automatic paid continuation.")
        if args.execute and settings.mock_models:
            raise ModelError(
                "Set MOCK_MODELS=0 explicitly before --execute. No paid request attempted."
            )
        initialize()
        seed_demo()
        player, clip = prepare(
            args.clip,
            args.start,
            args.duration,
            args.subject,
            args.description,
            args.team,
            args.number,
        )
        result = {
            "subject": player["name"],
            "clip": clip["url"],
            "duration": clip["duration"],
            "source_uploaded": False,
            "inference_calls_in_this_command": 0,
            "no_fantasy_transaction": True,
        }
        if args.execute:
            result["scan_id"] = enqueue_film(player, clip)
            if args.retry:
                retry_film(result["scan_id"])
            result["status"] = (
                "Explicit continuation queued; saved outputs reused and at most two additional calls."
                if args.retry
                else "Queued or reused existing diagnostic. The separate live worker performs at most four model calls."
            )
        else:
            result["status"] = "Prepared locally only. Use --execute to queue live inference."
        report = settings.data_dir / "cache" / "live-film" / "latest.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    except (ValueError, ModelError, OSError, subprocess.SubprocessError) as error:
        print(
            json.dumps(
                {
                    "error": (
                        str(error)
                        if isinstance(error, (ValueError, ModelError))
                        else type(error).__name__
                    ),
                    "inference_calls_in_this_command": 0,
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
