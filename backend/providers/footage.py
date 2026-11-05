"""Catalog and opt-in public footage imports with separate source and identity evidence."""

from datetime import date, datetime, timezone
from hashlib import sha256
import ipaddress
import json
from pathlib import Path
import re
import socket
import subprocess
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from backend.config import settings
from backend.db.database import session_scope
from backend.db.schema import Clip
from backend.services.clips import LocalClipProvider, local_path, prepare_clip, source_key
from backend.services.player_identity import normalized_name


class FootageError(ValueError):
    def __init__(self, message, stop_source=False):
        super().__init__(message)
        self.stop_source = stop_source


class CatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nba_id: str = Field(pattern=r"^\d{1,12}$")
    game_date: date
    title: str = Field(min_length=1, max_length=250)
    source_ref: str = Field(min_length=8, max_length=1000)
    rights_reference: str = Field(min_length=10, max_length=1000)
    path: str | None = None
    url: str | None = None
    start_seconds: float = Field(0, ge=0, le=3600)
    duration_seconds: float = Field(5, gt=0, le=30)

    @model_validator(mode="after")
    def one_location(self):
        if bool(self.path) == bool(self.url):
            raise ValueError("A catalog entry needs one media location.")
        return self


def recent_date(value, today=None):
    current = today or datetime.now(timezone.utc).date()
    return 0 <= (current - value).days <= settings.footage_max_age_days


def public_media_url(url, allowed_hosts=None):
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
        or parts.hostname
        not in (settings.footage_allowed_hosts if allowed_hosts is None else allowed_hosts)
    ):
        raise FootageError("Media host is not authorized for this footage library.")
    try:
        addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise FootageError("Private network media addresses are not permitted.")
    except OSError:
        raise FootageError("Could not resolve the authorized media host.") from None
    return url


class AutomaticClipProvider:
    def __init__(self, factory=None, client=None):
        self.factory, self.client = factory, client
        self.catalog = None
        self.preparations_left = settings.max_clips_per_candidate * 2

    def entries(self):
        if self.catalog is not None:
            return self.catalog
        path = settings.footage_catalog_path
        if not path:
            self.catalog = []
            return self.catalog
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                raise FootageError("Footage catalog exceeds the size limit.")
            raw = json.loads(path.read_text())
            if not isinstance(raw, list) or len(raw) > 2000:
                raise FootageError("Footage catalog must contain at most 2,000 entries.")
            self.catalog = [CatalogEntry.model_validate(row) for row in raw]
            return self.catalog
        except (OSError, ValueError):
            raise FootageError(
                "The configured footage library could not be read. Check its catalog format."
            ) from None

    def find(self, player, excluded_ids=(), excluded_hashes=(), excluded_sources=()):
        skipped = set(excluded_ids)
        while local := LocalClipProvider(False, self.factory).find(
            player["id"], skipped, excluded_hashes, excluded_sources
        ):
            if local["id"] in skipped:
                break
            if (not settings.public_footage_analysis_enabled or local.get("game_date")) and (
                not local.get("public_source")
                or (local.get("source_identity") or {}).get("version") == 2
            ):
                return local
            skipped.add(local["id"])
        if not player.get("nba_id"):
            return None
        entries = sorted(
            (
                e
                for e in self.entries()
                if e.nba_id == str(player["nba_id"]) and recent_date(e.game_date)
            ),
            key=lambda e: e.game_date,
            reverse=True,
        )
        for entry in entries:
            if (
                entry.source_ref in excluded_sources
                or source_key(
                    {
                        "source_ref": entry.source_ref,
                        "source_span": {
                            "start": entry.start_seconds,
                            "end": entry.start_seconds
                            + min(settings.max_clip_seconds, entry.duration_seconds),
                        },
                    }
                )
                in excluded_sources
            ):
                continue
            clip = self.prepare_entry(entry, player, excluded_hashes=excluded_hashes)
            if clip and clip["id"] not in excluded_ids:
                return clip
        return None

    def import_public(
        self, player, sources, excluded_ids=(), excluded_hashes=(), excluded_sources=()
    ):
        if not settings.public_footage_analysis_enabled:
            return None
        for source in sources:
            if (
                source.get("publisher") != "ESPN"
                or not source.get("_media_url")
                or source.get("url") in excluded_sources
            ):
                continue
            entry = CatalogEntry(
                nba_id=str(player.get("nba_id") or "0"),
                game_date=source["game_date"],
                title=source["title"],
                source_ref=source["url"],
                url=source["_media_url"],
                rights_reference="User enabled public-source private analysis; publisher ownership retained. This is not a license grant.",
                start_seconds=source.get("_start_seconds", 0),
                duration_seconds=source.get("_duration_seconds", settings.max_clip_seconds),
            )
            if (
                source_key(
                    {
                        "source_ref": entry.source_ref,
                        "source_span": {
                            "start": entry.start_seconds,
                            "end": entry.start_seconds
                            + min(settings.max_clip_seconds, entry.duration_seconds),
                        },
                    }
                )
                in excluded_sources
            ):
                continue
            if not recent_date(entry.game_date):
                continue
            # Preserve the original one-entry API for existing adapters.
            options = {"excluded_hashes": excluded_hashes} if excluded_hashes else {}
            try:
                clip = self.prepare_entry(entry, player, public=True, **options)
            except FootageError as error:
                if error.stop_source:
                    raise
                continue
            if not clip or clip.get("id") in excluded_ids:
                continue
            if source.get("_identity_context"):
                with session_scope(self.factory) as session:
                    row = session.get(Clip, clip["id"])
                    row.data = {**row.data, "source_identity": source["_identity_context"]}
                    clip = dict(row.data)
            return clip
        return None

    def prepare_entry(self, entry, player, public=False, excluded_hashes=()):
        if self.preparations_left <= 0:
            return None
        self.preparations_left -= 1
        directory = settings.data_dir / "uploads"
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / (uuid4().hex + ".input")
        processed = directory / (uuid4().hex + ".mp4")
        client = self.client
        try:
            if entry.path:
                root = (
                    settings.footage_media_root or settings.footage_catalog_path.parent
                ).resolve()
                source = (root / entry.path).resolve()
                if not source.is_relative_to(root) or not source.is_file():
                    raise FootageError(
                        "The matching footage file is missing from the authorized library."
                    )
            else:
                url = public_media_url(
                    entry.url,
                    {"espnmedia-cdn.akamaized.net", "media.video-cdn.espn.com"} if public else None,
                )
                client = client or httpx.Client(timeout=30, follow_redirects=False)
                with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise FootageError(
                            f"Footage source returned HTTP {response.status_code}; no automatic retry was made.",
                            stop_source=response.status_code in {401, 403, 429},
                        )
                    total = 0
                    with temporary.open("wb") as out:
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > settings.max_upload_mb * 1024 * 1024:
                                raise FootageError("Footage download exceeds the size limit.")
                            out.write(chunk)
                source = temporary
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    str(entry.start_seconds),
                    "-i",
                    str(source),
                    "-t",
                    str(min(settings.max_clip_seconds, entry.duration_seconds)),
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
                    str(processed),
                ],
                capture_output=True,
                check=True,
                timeout=90,
            )
            if sha256(processed.read_bytes()).hexdigest() in excluded_hashes:
                processed.unlink(missing_ok=True)
                return None
            clip = prepare_clip(processed, player["id"], False, self.factory)
            if local_path(clip["url"]) != processed.resolve():
                # prepare_clip reused the existing content-hash record. Only
                # discard this import's unused output, never the retained clip.
                processed.unlink(missing_ok=True)
            provenance = {
                "source": (
                    "Public ESPN highlight · user-enabled private analysis"
                    if public
                    else "Authorized footage library"
                ),
                "source_ref": entry.source_ref,
                "source_title": entry.title,
                "game_date": str(entry.game_date),
                "rights_reference": entry.rights_reference,
                "automatically_matched": True,
                "identity_status": "pending_visual_verification",
                "public_source": public,
                "source_span": {
                    "start": entry.start_seconds,
                    "end": entry.start_seconds + clip["duration"],
                },
            }
            with session_scope(self.factory) as session:
                row = session.get(Clip, clip["id"])
                row.data = {**row.data, **provenance}
                clip = dict(row.data)
            return clip
        except FootageError:
            processed.unlink(missing_ok=True)
            raise
        except (httpx.HTTPError, subprocess.SubprocessError):
            processed.unlink(missing_ok=True)
            raise FootageError(
                "The matching footage could not be prepared. No substitute footage was used."
            ) from None
        finally:
            temporary.unlink(missing_ok=True)
            if client and client is not self.client:
                client.close()


class ESPNFootageDiscovery:
    """Bounded, cached official metadata. It never retrieves video bytes."""

    base = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"

    def __init__(self, client=None, max_requests=6, force_refresh=False):
        self.client = client or httpx.Client(timeout=12, follow_redirects=False)
        self.owned = client is None
        self.remaining = max_requests
        self.cache = {}
        self.force_refresh = force_refresh
        self.request_count = 0
        self.cache_hits = 0

    def close(self):
        if self.owned:
            self.client.close()

    def get(self, path):
        if path in self.cache:
            self.cache_hits += 1
            return self.cache[path]
        key = sha256(path.encode()).hexdigest()
        dest = settings.data_dir / "cache" / "footage-discovery" / (key + ".json")
        try:
            record = json.loads(dest.read_text())
            age = (
                datetime.now(timezone.utc) - datetime.fromisoformat(record["fetched_at"])
            ).total_seconds()
            if 0 <= age < 1800 and not self.force_refresh:
                self.cache_hits += 1
                self.cache[path] = record["data"]
                return record["data"]
        except (OSError, ValueError, KeyError):
            pass
        if self.remaining <= 0:
            return {}
        self.remaining -= 1
        self.request_count += 1
        try:
            response = self.client.get(self.base + path)
            if response.status_code in {403, 429}:
                self.remaining = 0
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return {}
            dest.parent.mkdir(parents=True, exist_ok=True)
            temp = dest.with_name(uuid4().hex + ".tmp")
            temp.write_text(
                json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "data": data})
            )
            temp.replace(dest)
            self.cache[path] = data
            return data
        except (httpx.HTTPError, ValueError):
            return {}

    def find(self, player, include_media=False):
        team = str(player.get("team", "")).upper()
        alias = {"NYK": "NY", "GSW": "GS", "NOP": "NO", "SAS": "SA", "UTA": "UTAH", "PHX": "PHX"}
        team = alias.get(team, team)
        if not re.fullmatch(r"[A-Z]{2,4}", team):
            return []
        schedule = self.get("/teams/" + team.lower() + "/schedule")
        games = []
        for game in schedule.get("events", []):
            try:
                stamp = datetime.fromisoformat(game["date"].replace("Z", "+00:00"))
                if recent_date(stamp.date()) and any(
                    c.get("status", {}).get("type", {}).get("completed")
                    for c in game.get("competitions", [])
                ):
                    games.append(game)
            except (ValueError, KeyError):
                continue
        links = []
        name = normalized_name(player["name"])
        for game in sorted(games, key=lambda g: g["date"], reverse=True)[:3]:
            if not re.fullmatch(r"\d{1,15}", str(game.get("id", ""))):
                continue
            summary = self.get("/summary?event=" + str(game["id"]))
            for video in summary.get("videos", []):
                headline = str(video.get("headline", ""))
                text = normalized_name(headline + " " + str(video.get("description", "")))
                if not re.search(r"(?:^| )" + re.escape(name) + r"(?: |$)", text):
                    continue
                vid = str(video.get("id", ""))
                if not re.fullmatch(r"\d{1,15}", vid):
                    continue
                links.append(
                    {
                        "title": headline,
                        "url": "https://www.espn.com/video/clip/_/id/" + vid,
                        "game_date": str(
                            datetime.fromisoformat(game["date"].replace("Z", "+00:00"))
                            .astimezone(ZoneInfo("America/New_York"))
                            .date()
                        ),
                        "publisher": "ESPN",
                        "status": "viewing_link_only",
                    }
                )
                from backend.services.clip_identity import game_identity_context

                links[-1]["_identity_context"] = game_identity_context(
                    summary, game["id"], links[-1]["game_date"], player
                )
                duration = video.get("duration")
                if type(duration) in (int, float) and 0 < duration <= 60:
                    links[-1]["_source_duration"] = duration
                if include_media and str(video.get("source", "")).lower() == "espn":
                    source = video.get("links", {}).get("source", {})
                    media = (source.get("HD") or {}).get("href") or source.get("href")
                    if isinstance(media, str) and urlsplit(media).path.lower().endswith(".mp4"):
                        links[-1]["_media_url"] = media
        unique = list({link["url"]: link for link in links}.values())[:3]
        # If only one publisher highlight exists, a genuinely different time
        # range can supply another camera view. It remains the same play/source.
        if include_media and len(unique) == 1:
            source = unique[0]
            length = source.get("_source_duration", 0)
            seconds = settings.max_clip_seconds
            if source.get("_media_url") and length >= seconds * 2:
                unique.append(
                    {
                        **source,
                        "title": source["title"] + " · later excerpt",
                        "_start_seconds": length - seconds,
                        "_duration_seconds": seconds,
                        "excerpt_of_same_highlight": True,
                    }
                )
        return unique
