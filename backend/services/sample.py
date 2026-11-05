"""Original procedural footage; no downloaded sports footage or likenesses.

The same geometric scene drives the video and mock observations. This is a
deterministic simulation, never a claim that SAM processed a real NBA game.
"""

import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from backend.config import settings

WIDTH, HEIGHT, FPS, SECONDS = 960, 540, 12, 8


def scene(player_id: str, frame: int) -> list[dict]:
    t = frame / FPS
    variant = int(player_id[-1]) if player_id[-1].isdigit() else 1
    x = 320 + t * 30
    y = 310 - 58 * math.sin(t * 0.5)
    gap = {1: 118, 2: 68, 3: 36, 4: 94, 5: 65, 6: 40}.get(variant, 65)
    near = (frame // 12) % 4 < (3 if variant == 1 else 2 if variant in (2, 4) else 1)
    centers = [
        (1, "target", x, y),
        (2, "defender", x + gap, y - 16),
        (3, "defender", 690 - t * 13, 190 + t * 8),
        (4, "ball", x + 19 if near else x - 155, y + 12 if near else 190),
    ]
    objects = []
    for oid, role, cx, cy in centers:
        rw, rh = (8, 8) if role == "ball" else (19, 29)
        objects.append(
            {
                "id": oid,
                "role": role,
                "box": [cx - rw, cy - rh, cx + rw, cy + rh],
                "centroid": [cx, cy],
                "mask_url": None,
                "mask_polygon": [
                    [cx - rw, cy - rh + 9],
                    [cx, cy - rh],
                    [cx + rw, cy - rh + 9],
                    [cx + rw - 3, cy + rh],
                    [cx - rw + 3, cy + rh],
                ],
            }
        )
    return objects


def draw_scene(player_id: str, frame: int) -> Image.Image:
    im = Image.new("RGB", (WIDTH, HEIGHT), "#222d26")
    d = ImageDraw.Draw(im)
    for x in range(30, 940, 22):
        d.rectangle((x, 65, x + 21, 480), fill="#4b4938" if (x // 22) % 2 else "#4e4c3b")
    line = "#aaa58b"
    d.rectangle((42, 78, 918, 468), outline=line, width=2)
    d.line((480, 78, 480, 468), fill=line, width=2)
    d.ellipse((419, 212, 541, 334), outline=line, width=2)
    for left in [True, False]:
        bx = 42 if left else 764
        d.rectangle((bx, 193, bx + 154, 353), outline=line, width=2)
        d.ellipse(
            (bx + 94 if left else bx - 59, 218, bx + 212 if left else bx + 59, 328),
            outline=line,
            width=2,
        )
        d.arc(
            (-156 if left else 715, 92, 245 if left else 1116, 452),
            -90 if left else 90,
            90 if left else 270,
            fill=line,
            width=2,
        )
        rimx = 74 if left else 886
        d.ellipse((rimx - 7, 267, rimx + 7, 281), outline="#d38c4c", width=3)
    d.text(
        (42, 24),
        "TAPE GRADE  /  ORIGINAL SCHEMATIC SIMULATION",
        fill="#b0b9ac",
        font=ImageFont.load_default(size=14),
    )
    d.text(
        (42, 504),
        f"FICTIONAL PLAYER {player_id.upper()}    •    {frame/FPS:05.2f}s    /    NO REAL GAME FOOTAGE",
        fill="#a1ad9d",
        font=ImageFont.load_default(size=13),
    )
    for cx, cy in [(225, 130), (286, 407), (750, 409)]:
        d.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), fill="#bcb8a0", outline="#d5d0ba", width=2)
    for obj in scene(player_id, frame):
        x, y = obj["centroid"]
        if obj["role"] == "ball":
            d.ellipse((x - 7, y - 7, x + 7, y + 7), fill="#e99950", outline="#422819", width=2)
            d.line((x - 6, y, x + 6, y), fill="#422819")
        else:
            color = "#d9dbc7" if obj["role"] == "target" else "#242c2a"
            d.ellipse((x - 22, y + 19, x + 27, y + 31), fill="#373b2e")
            d.polygon(obj["mask_polygon"], fill=color, outline="#798477")
            d.ellipse((x - 9, y - 31, x + 9, y - 13), fill="#ae8868")
            jersey = {"c1": 4, "c2": 12, "c3": 2, "c4": 34, "c5": 18, "c6": 6}.get(player_id, 4)
            d.text(
                (x - 5, y - 6),
                str(jersey) if obj["role"] == "target" else str(obj["id"] + 8),
                fill="#313b31" if obj["role"] == "target" else "#c9c7b1",
                font=ImageFont.load_default(size=16),
            )
    return im


def ensure_sample(player_id: str, directory: Path | None = None) -> Path:
    directory = directory or settings.data_dir / "samples"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"schematic-v2-{player_id}.mp4"
    if path.exists():
        return path
    tmp = path.with_suffix(".tmp.mp4")
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{WIDTH}x{HEIGHT}",
            "-r",
            str(FPS),
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(tmp),
        ],
        stdin=subprocess.PIPE,
    )
    try:
        for f in range(FPS * SECONDS):
            process.stdin.write(draw_scene(player_id, f).tobytes())
        process.stdin.close()
        if process.wait(timeout=30) != 0:
            raise RuntimeError("Sample video encoder failed. Check ffmpeg installation.")
        tmp.replace(path)
    except Exception:
        process.kill()
        raise
    return path
