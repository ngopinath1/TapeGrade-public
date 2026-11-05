"""Documented NBA /v1/stats adapter. Never fills absent technical/flagrant fouls."""

from datetime import datetime, timezone
from hashlib import sha256
import json
import time
from uuid import uuid4

import httpx

from backend.config import settings
from backend.providers.stats_base import Athlete, BoxScore, GameRecord, StatsBatch


class StatsProviderError(ValueError):
    pass


def minutes(value):
    if value is None or value == "":
        return None
    if isinstance(value, str) and ":" in value:
        parts = value.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts) or int(parts[1]) >= 60:
            raise ValueError("Invalid minutes")
        return int(parts[0]) + int(parts[1]) / 60
    return float(value)


class BallDontLieStatsProvider:
    BASE = "https://api.balldontlie.io/v1"

    def __init__(self, client=None):
        self.client = client or httpx.Client(timeout=15)

    def fetch(self, start, end, season):
        key = settings.balldontlie_api_key.get_secret_value()
        if not key:
            raise StatsProviderError(
                "Configure BALLDONTLIE_API_KEY locally before refreshing. Game logs require a suitable NBA plan; no subscription was created."
            )
        params = {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "seasons[]": season,
            "season_type": "regular",
            "period": 0,
            "per_page": 100,
        }
        records, athletes, cursors, cursor = {}, {}, set(), None
        fetched = datetime.now(timezone.utc)
        started = time.monotonic()
        for page in range(settings.stats_max_pages):
            if time.monotonic() - started > settings.stats_timeout_seconds:
                raise StatsProviderError(
                    "Statistics refresh time budget reached. Last complete snapshot retained."
                )
            try:
                response = self.client.get(
                    self.BASE + "/stats",
                    params={**params, **({"cursor": cursor} if cursor is not None else {})},
                    headers={"Authorization": key},
                )
                if response.status_code == 429:
                    retry = response.headers.get("Retry-After", "later")
                    retry = retry if retry.isdigit() else "later"
                    raise StatsProviderError(
                        f"Statistics rate limit reached; retry after {retry}. No automatic retry; last snapshot retained."
                    )
                if response.status_code in (401, 403):
                    raise StatsProviderError(
                        "Statistics access denied. Check the local key and NBA game-stat plan. Last snapshot retained."
                    )
                response.raise_for_status()
                raw = response.json()
                if not isinstance(raw.get("data"), list) or not isinstance(raw.get("meta"), dict):
                    raise ValueError("Invalid page")
                encoded = json.dumps(raw, sort_keys=True).encode()
                digest = sha256(encoded).hexdigest()
                path = settings.data_dir / "cache" / "stats" / (digest + ".json")
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_name(uuid4().hex + ".tmp")
                temp.write_bytes(encoded)
                temp.replace(path)
                source = "cache:stats/" + path.name
                for row in raw["data"]:
                    p, game = row["player"], row["game"]
                    pid = str(p["id"])
                    athletes[pid] = Athlete(
                        id=pid,
                        name=p["first_name"] + " " + p["last_name"],
                        team=(row.get("team") or {}).get("abbreviation"),
                        jersey=p.get("jersey_number"),
                    )
                    stats = {k: row.get(k) for k in BoxScore.model_fields}
                    stats.update(to=row.get("turnover"), tpm=row.get("fg3m"), tpa=row.get("fg3a"))
                    # 'pf' is personal fouls. No tf/ff aliases are established by the docs.
                    stats.update(tf=None, ff=None)
                    mins = minutes(row.get("min"))
                    final = game.get("status_state") == "final" or game.get("status") == "Final"
                    rec = GameRecord(
                        provider="balldontlie",
                        athlete_id=pid,
                        game_id=str(game["id"]),
                        game_date=str(game["date"])[:10],
                        season=game["season"],
                        season_type="regular",
                        status=(
                            "postponed"
                            if game.get("postponed")
                            else "final" if final else "in_progress"
                        ),
                        participation="played" if mins is not None and mins > 0 else "unknown",
                        minutes=mins,
                        stats=BoxScore(**stats),
                        fetched_at=fetched,
                        source_ref=source,
                    )
                    records[(rec.game_id, rec.athlete_id)] = rec
                nxt = raw["meta"].get("next_cursor")
                if nxt is None:
                    return StatsBatch(
                        provider="balldontlie",
                        start_date=start,
                        end_date=end,
                        fetched_at=fetched,
                        complete=True,
                        synthetic=False,
                        source_ref="https://api.balldontlie.io/v1/stats",
                        athletes=list(athletes.values()),
                        games=list(records.values()),
                    )
                if not isinstance(nxt, int) or nxt in cursors:
                    raise ValueError("Invalid cursor")
                cursors.add(nxt)
                cursor = nxt
            except StatsProviderError:
                raise
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise StatsProviderError(
                    "Statistics provider returned unavailable or invalid data. Last complete snapshot retained."
                ) from None
        raise StatsProviderError(
            "Statistics page budget reached before complete coverage. Last complete snapshot retained."
        )
