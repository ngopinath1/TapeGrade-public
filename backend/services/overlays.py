from pathlib import Path

from PIL import Image, ImageDraw

from backend.config import settings
from backend.services.clips import local_path, media_url

COLORS = {"target": "#b6f36c", "defender": "#6da5e7", "ball": "#ffb564", "unknown": "#b8b8b8"}


def create_overlays(clip: dict, tracking, key: str) -> list[str]:
    directory = settings.data_dir / "cache" / "overlays" / key
    directory.mkdir(parents=True, exist_ok=True)
    urls = []
    for i, source in enumerate(clip["frames"]):
        frame = (
            min(tracking.frames, key=lambda f: abs(f.time - source["time"]))
            if tracking.frames
            else None
        )
        image = Image.open(local_path(source["url"])).convert("RGBA")
        if frame and abs(frame.time - source["time"]) <= 0.51 / tracking.fps:
            scale_x, scale_y = image.width / tracking.width, image.height / tracking.height
            for obj in frame.objects:
                color = COLORS[obj.role]
                if obj.mask_url:
                    mask = Image.open(local_path(obj.mask_url)).convert("L")
                    # SAM masks are box-local; place into the actual inclusive box.
                    b = obj.box
                    size = (
                        max(1, round((b[2] - b[0] + 1) * scale_x)),
                        max(1, round((b[3] - b[1] + 1) * scale_y)),
                    )
                    tinted = Image.new("RGBA", size, color)
                    tinted.putalpha(mask.resize(size).point(lambda p: round(p * 0.3)))
                    image.alpha_composite(tinted, (round(b[0] * scale_x), round(b[1] * scale_y)))
                draw = ImageDraw.Draw(image, "RGBA")
                if obj.mask_polygon:
                    draw.polygon(
                        [(x * scale_x, y * scale_y) for x, y in obj.mask_polygon], fill=color + "44"
                    )
                draw.rectangle(
                    [
                        obj.box[0] * scale_x,
                        obj.box[1] * scale_y,
                        obj.box[2] * scale_x,
                        obj.box[3] * scale_y,
                    ],
                    outline=color,
                    width=2,
                )
                draw.text(
                    (obj.box[0] * scale_x, max(0, obj.box[1] * scale_y - 16)),
                    f"{obj.role.upper()} #{obj.id}",
                    fill=color,
                )
        path = directory / f"{i}.jpg"
        image.convert("RGB").save(path, quality=85)
        urls.append(media_url(path))
    return urls
