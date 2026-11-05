"""Sportradar NBA v8 closed-game logs, cached and bounded at one request/sec.

Official contracts: NBA Schedule, Game Summary, API Authentication & Headers.
All source bodies stay in ignored cache; authentication headers never enter receipts.
"""

from datetime import datetime, timezone
from hashlib import sha256
import json
import time
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx

from backend.config import settings
from backend.providers.stats_base import Athlete, BoxScore, GameRecord, StatsBatch
from backend.providers.stats_balldontlie import StatsProviderError, minutes

EASTERN = ZoneInfo("America/New_York")
FIELDS = {
    "pts": "points",
    "reb": "rebounds",
    "ast": "assists",
    "stl": "steals",
    "blk": "blocks",
    "to": "turnovers",
    "tpm": "three_points_made",
    "tpa": "three_points_att",
    "fgm": "field_goals_made",
    "fga": "field_goals_att",
    "ftm": "free_throws_made",
    "fta": "free_throws_att",
    "oreb": "offensive_rebounds",
    "dreb": "defensive_rebounds",
    "pf": "personal_fouls",
    "ff": "flagrant_fouls",
}


def game_date(value):
    if not isinstance(value, str):
        raise ValueError("Missing game time")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Game time must include a timezone")
    return stamp.astimezone(EASTERN).date()


def canonical_id(value):
    if not isinstance(value, str):
        raise ValueError("Invalid provider ID")
    return str(UUID(value))


def normalize_summary(raw, expected_id, season, observed_at, source_ref):
    """No personal/team/coach fouls or undocumented defaults substitute for tf/ff."""
    if canonical_id(raw["id"]) != expected_id or raw["status"] != "closed":
        raise ValueError("Unexpected or unfinished game")
    if raw["season"]["year"] != season or raw["season"]["type"] != "REG":
        raise ValueError("Unexpected season")
    when = game_date(raw["scheduled"])
    athletes, games, seen = [], [], set()
    for side in ("home", "away"):
        team = raw[side]
        if not isinstance(team["players"], list) or not team["players"]:
            raise ValueError("Missing player coverage")
        for p in team["players"]:
            pid = canonical_id(p["id"])
            if pid in seen:
                raise ValueError("Duplicate game/player observation")
            seen.add(pid)
            athletes.append(
                Athlete(
                    id=pid,
                    sportradar_id=pid,
                    name=p["full_name"],
                    team=team.get("alias"),
                    nba_id=str(p["reference"]) if p.get("reference") is not None else None,
                    jersey=p.get("jersey_number"),
                )
            )
            stats = p.get("statistics") or {}
            values = {name: stats.get(field) for name, field in FIELDS.items()}
            notes = []
            # Sportradar separates unsportsmanlike and non-unsportsmanlike techs.
            # Their treatment in Sleeper is not established for nonzero non-USP
            # events. Zero is explicit evidence, so ordinary games are unambiguous.
            non_usp = stats.get("tech_fouls_non_unsportsmanlike")
            values["tf"] = (
                stats.get("tech_fouls") if type(non_usp) is int and non_usp == 0 else None
            )
            if type(non_usp) is int and non_usp > 0:
                notes.append(
                    "Non-unsportsmanlike technical fouls require Sleeper scoring verification; TF withheld."
                )
            participation = (
                "played"
                if p.get("played") is True
                else (
                    "dnp"
                    if (
                        p.get("played") is False
                        or p.get("active") is False
                        or isinstance(p.get("not_playing_reason"), str)
                        and p["not_playing_reason"].strip()
                    )
                    else "unknown"
                )
            )
            games.append(
                GameRecord(
                    provider="sportradar",
                    athlete_id=pid,
                    game_id=expected_id,
                    game_date=when,
                    season=season,
                    season_type="regular",
                    status="final",
                    participation=participation,
                    minutes=minutes(stats.get("minutes")),
                    stats=BoxScore(**values),
                    fetched_at=observed_at,
                    source_ref=source_ref,
                    quality_notes=notes,
                )
            )
    return athletes, games


class SportradarStatsProvider:
    BASE = "https://api.sportradar.com/nba"

    def __init__(
        self,
        client=None,
        *,
        access_level=None,
        request_limit=None,
        timeout_seconds=None,
        request_interval=None,
        monotonic=None,
        sleep=None,
    ):
        self.client = client or httpx.Client(timeout=15)
        self.access = access_level or settings.sportradar_access_level
        if self.access not in {"trial", "production"}:
            raise ValueError("Unsupported Sportradar access level")
        self.limit = request_limit or settings.stats_max_pages
        self.timeout = timeout_seconds or settings.stats_timeout_seconds
        self.interval = request_interval or settings.sportradar_min_interval_seconds
        if self.interval < 1.05:
            raise ValueError("Sportradar pacing must respect the trial QPS limit")
        self.monotonic = monotonic or time.monotonic
        self.sleep = sleep or time.sleep
        self.calls, self.hits = 0, 0
        self.request_audit = []
        self.last_request = None
        self.started = self.monotonic()
        self.root = settings.data_dir / "cache" / "stats" / "sportradar"

    def _manifest(self, path):
        digest = sha256((self.access + ":" + path).encode()).hexdigest()
        return self.root / "requests" / (digest + ".json")

    def cached_response(self, path, ttl):
        try:
            manifest = json.loads(self._manifest(path).read_text())
            stamp = datetime.fromisoformat(manifest["fetched_at"])
            age = (datetime.now(timezone.utc) - stamp).total_seconds()
            digest = manifest["digest"]
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                return None
            body = (self.root / (digest + ".json")).read_bytes()
            if 0 <= age < ttl and sha256(body).hexdigest() == digest:
                return json.loads(body), stamp, "cache:stats/sportradar/" + digest + ".json"
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def store_response(self, path, data, fetched_at):
        encoded = json.dumps(data, sort_keys=True).encode()
        digest = sha256(encoded).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        body_path = self.root / (digest + ".json")
        temp = body_path.with_name(uuid4().hex + ".tmp")
        temp.write_bytes(encoded)
        temp.replace(body_path)
        manifest = self._manifest(path)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        temp = manifest.with_name(uuid4().hex + ".tmp")
        temp.write_text(json.dumps({"fetched_at": fetched_at.isoformat(), "digest": digest}))
        temp.replace(manifest)
        return data, fetched_at, "cache:stats/sportradar/" + digest + ".json"

    def get(self, path, ttl):
        key = settings.sportradar_api_key.get_secret_value()
        if not key:
            raise StatsProviderError(
                "SPORTRADAR_API_KEY is not configured locally. No request was made."
            )
        cached = self.cached_response(path, ttl)
        if cached:
            self.hits += 1
            return cached
        if self.calls >= self.limit:
            raise StatsProviderError(
                "Sportradar request budget reached before complete coverage. Last snapshot retained."
            )
        delay = (
            max(0, self.interval - (self.monotonic() - self.last_request))
            if self.last_request is not None
            else 0
        )
        remaining = self.timeout - (self.monotonic() - self.started) - delay
        if remaining <= 0:
            raise StatsProviderError(
                "Sportradar refresh time budget reached. Last snapshot retained."
            )
        if delay:
            self.sleep(delay)
        self.calls += 1
        try:
            response = self.client.get(
                self.BASE + "/" + self.access + "/v8/en/" + path,
                headers={"x-api-key": key, "accept": "application/json"},
                timeout=min(15, remaining),
            )
            self.request_audit.append(
                {
                    "path": path,
                    "status": response.status_code,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "rate_limits": {
                        k: v
                        for k, v in response.headers.items()
                        if k.startswith("x-plan-") and v.replace(".", "", 1).isdigit()
                    },
                }
            )
            if response.status_code in {401, 403}:
                raise StatsProviderError(
                    "Sportradar access denied. Confirm the key has NBA API trial/production access. Last snapshot retained."
                )
            if response.status_code == 429:
                retry = response.headers.get("Retry-After", "later")
                retry = retry if retry.isdigit() else "later"
                raise StatsProviderError(
                    f"Sportradar rate limit reached; retry after {retry}. No automatic retry; last snapshot retained."
                )
            response.raise_for_status()
            raw = response.json()
            if not isinstance(raw, dict):
                raise ValueError("Invalid JSON document")
            if key in json.dumps(raw):
                raise ValueError("Credential-bearing response rejected")
            return self.store_response(path, raw, datetime.now(timezone.utc))
        except StatsProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            raise StatsProviderError(
                "Sportradar is unavailable or returned invalid data. Last complete snapshot retained."
            ) from None
        finally:
            # Trial QPS enforcement can include network/response time. Leave a
            # full interval after completion, rather than between request starts.
            self.last_request = self.monotonic()

    def fetch(self, start, end, season):
        self.calls, self.hits = 0, 0
        self.request_audit = []
        self.started, self.last_request = self.monotonic(), None
        try:
            schedule, _, _ = self.get(f"games/{season}/REG/schedule.json", 600)
            if schedule["season"]["year"] != season or schedule["season"]["type"] != "REG":
                raise ValueError("Unexpected schedule season")
            eligible = {}
            for g in schedule["games"]:
                if g["status"] == "closed" and start <= game_date(g["scheduled"]) <= end:
                    gid = canonical_id(g["id"])
                    if gid in eligible and eligible[gid] != g:
                        raise ValueError("Conflicting duplicate schedule game")
                    eligible[gid] = g
            if not eligible:
                raise StatsProviderError(
                    "No closed NBA regular-season games in the requested window. Last snapshot retained."
                )
            paths = [
                (
                    gid,
                    f"games/{gid}/summary.json",
                    14400 if (end - game_date(g["scheduled"])).days > 7 else 600,
                )
                for gid, g in sorted(eligible.items(), key=lambda pair: pair[1]["scheduled"])
            ]
            # Refuse incomplete windows before starting the expensive game loop.
            uncached = sum(self.cached_response(path, ttl) is None for _, path, ttl in paths)
            if self.calls + uncached > self.limit:
                raise StatsProviderError(
                    "Complete Sportradar window exceeds the request budget. Reduce STATS_WINDOW_DAYS or explicitly increase STATS_MAX_PAGES. Last snapshot retained."
                )
            athletes, records = {}, []
            for gid, path, ttl in paths:
                raw, stamp, source_ref = self.get(path, ttl)
                people, games = normalize_summary(raw, gid, season, stamp, source_ref)
                if any(not start <= g.game_date <= end for g in games):
                    raise ValueError("Game moved outside the requested window")
                for p in people:
                    athletes[p.id] = p
                records.extend(games)
            return StatsBatch(
                provider="sportradar",
                start_date=start,
                end_date=end,
                fetched_at=datetime.now(timezone.utc),
                complete=True,
                synthetic=False,
                source_ref=self.BASE
                + "/"
                + self.access
                + "/v8/en/games/"
                + str(season)
                + "/REG/schedule.json",
                athletes=list(athletes.values()),
                games=records,
                request_count=self.calls,
                cache_hits=self.hits,
            )
        except StatsProviderError:
            raise
        except (KeyError, ValueError, TypeError):
            raise StatsProviderError(
                "Sportradar returned inconsistent season, player or box-score data. Last complete snapshot retained."
            ) from None
