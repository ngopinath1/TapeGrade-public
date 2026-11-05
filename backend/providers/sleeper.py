from datetime import datetime, timezone
import json
import math
import re
import time
from zoneinfo import ZoneInfo
from uuid import uuid4

import httpx

from backend.config import settings


def numeric(value):
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


class ProviderError(ValueError):
    pass


class SleeperLeagueProvider:
    BASE = "https://api.sleeper.app/v1"

    def __init__(self, client=None, username=None, league_id=None):
        self.client = client or httpx.Client(timeout=15)
        self.cache = {}
        self.username, self.league_id = username, league_id

    def get(self, path):
        cached = self.cache.get(path)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
        try:
            response = self.client.get(self.BASE + path)
            if response.status_code == 429:
                raise ProviderError(
                    "Sleeper rate limit reached. Please try again in a few minutes."
                )
            if response.status_code == 404:
                raise ProviderError("Sleeper account or league not found.")
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as e:
            if isinstance(e, ProviderError):
                raise
            raise ProviderError(
                "Sleeper is unavailable or returned invalid data. The sample NBA league is still available."
            ) from None
        if data is None:
            raise ProviderError("Sleeper account not found. Check the username.")
        self.cache[path] = (time.monotonic(), data)
        return data

    def connect(self, username, season=None, league_id=None):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", username):
            raise ProviderError("Enter a valid Sleeper username.")
        user = self.get("/user/" + username)
        if not isinstance(user, dict) or not isinstance(user.get("user_id"), str):
            raise ProviderError("Sleeper returned an invalid user record.")
        if league_id:
            snapshot = self.snapshot_for(user, league_id)
            return {
                "user": {k: user.get(k) for k in ("user_id", "username", "display_name")},
                "connected": True,
                "snapshot": snapshot,
                "basketball_supported": "observed_by_league_id",
                "notice": snapshot["notice"],
            }
        year = season or datetime.now(ZoneInfo("America/New_York")).year
        leagues = self.get(f'/user/{user["user_id"]}/leagues/nfl/{year}')
        return {
            "user": user,
            "leagues": leagues,
            "season": year,
            "basketball_supported": False,
            "notice": "Sleeper publicly documents NFL-only league discovery. These are actual NFL league records, not basketball data. Use the fictional NBA sample for scouting.",
        }

    def league(self, league_id):
        if not re.fullmatch(r"\d{1,30}", league_id):
            raise ProviderError("Invalid Sleeper league ID.")
        league = self.get("/league/" + league_id)
        if not isinstance(league, dict) or league.get("sport") not in ("nfl", "nba"):
            raise ProviderError(
                "This sport is not supported by the documented public API integration."
            )
        if str(league.get("league_id")) != league_id:
            raise ProviderError("Sleeper returned a different or missing league ID.")
        rosters, users = self.get(f"/league/{league_id}/rosters"), self.get(
            f"/league/{league_id}/users"
        )
        if (
            not isinstance(rosters, list)
            or not isinstance(users, list)
            or any(not isinstance(r, dict) for r in rosters + users)
        ):
            raise ProviderError("Sleeper returned an invalid league roster/user response.")
        for roster in rosters:
            for field in ("players", "reserve", "taxi", "starters", "co_owners"):
                value = roster.get(field)
                if value is not None and (
                    not isinstance(value, list) or any(not isinstance(v, str) for v in value)
                ):
                    raise ProviderError("Sleeper returned invalid roster membership data.")
        return {
            "league": league,
            "rosters": rosters,
            "users": users,
            "source": "Sleeper public API · actual " + league["sport"].upper() + " data",
            "compatibility": (
                "Observed NBA league-ID compatibility; automatic NBA discovery is not documented."
                if league["sport"] == "nba"
                else "Documented NFL integration"
            ),
        }

    def players(self):
        """The documented player map is cached on disk for 24 hours, across restarts."""
        path = settings.data_dir / "cache" / "sleeper" / "nba-player-directory.json"
        try:
            cached = json.loads(path.read_text())
            if 0 <= time.time() - cached["fetched_at"] < 86400 and isinstance(cached["data"], dict):
                return cached["data"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        data = self.get("/players/nba")
        if (
            not isinstance(data, dict)
            or not data
            or any(not isinstance(p, dict) for p in data.values())
        ):
            raise ProviderError("Sleeper returned an invalid NBA player directory.")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps({"fetched_at": time.time(), "data": data}))
        temporary.replace(path)
        return data

    def snapshot_for(self, user, league_id):
        view = self.league(league_id)
        league, rosters = view["league"], view["rosters"]
        if league["sport"] != "nba":
            raise ProviderError(
                "Basketball scouting requires an NBA league ID. NFL leagues remain view-only."
            )
        uid = user["user_id"]
        mine = [r for r in rosters if r.get("owner_id") == uid or uid in (r.get("co_owners") or [])]
        if len(mine) != 1:
            raise ProviderError(
                "Could not identify exactly one roster for this username in the supplied league."
            )
        own = mine[0]
        own_ids = own.get("players") or []
        if not isinstance(own_ids, list) or any(not isinstance(pid, str) for pid in own_ids):
            raise ProviderError("Sleeper returned invalid roster player IDs.")
        directory = self.players()
        period = (league.get("settings") or {}).get("leg")
        matchup, points_warning = {}, None
        if isinstance(period, int) and 0 < period < 100:
            try:
                games = self.get(f"/league/{league_id}/matchups/{period}")
                if not isinstance(games, list) or any(not isinstance(g, dict) for g in games):
                    raise ProviderError("Sleeper returned invalid matchup data.")
                matchup = next((g for g in games if g.get("roster_id") == own.get("roster_id")), {})
            except ProviderError as error:
                points_warning = str(error)
        else:
            period = None
        scores = matchup.get("players_points") or {}
        if not isinstance(scores, dict):
            scores = {}
        internal_id = "sleeper:" + league_id

        def map_player(pid, on_roster=False):
            p = directory.get(pid) or {}
            name = " ".join(
                str(p.get(k) or "").strip() for k in ("first_name", "last_name")
            ).strip()
            positions = p.get("fantasy_positions") or ([p["position"]] if p.get("position") else [])
            return {
                "id": internal_id + ":" + pid,
                "external_id": pid,
                "birth_date": p.get("birth_date"),
                "nba_id": p.get("nba_id"),
                "sportradar_id": p.get("sportradar_id"),
                "name": name or f"Unknown player (Sleeper {pid})",
                "team": p.get("team") or "—",
                "positions": positions if isinstance(positions, list) else [],
                "number": numeric(p.get("number")),
                "is_demo": False,
                "fantasy_points": numeric(scores.get(pid)) if on_roster else None,
                "minutes": None,
                "previous_minutes": None,
                "stats": {},
                "trend": [],
                "lineup_status": (
                    "Starter"
                    if pid in (own.get("starters") or [])
                    else (
                        "Reserve"
                        if pid in (own.get("reserve") or [])
                        else "Bench" if on_roster else "Unrostered"
                    )
                ),
                "injury_status": p.get("injury_status"),
                "source": (
                    f"Sleeper NBA player directory; reported scoring-period {period} points"
                    if on_roster and period
                    else "Sleeper NBA player directory; no recent box-score data"
                ),
            }

        assigned = {
            pid
            for r in rosters
            for field in ("players", "reserve", "taxi")
            for pid in (r.get(field) or [])
            if isinstance(pid, str)
        }
        available = [
            map_player(pid)
            for pid, p in directory.items()
            if p.get("active") is True
            and p.get("team")
            and pid not in assigned
            and p.get("position") in {"PG", "SG", "SF", "PF", "C", "G", "F"}
        ]
        manager = next((u for u in view["users"] if u.get("user_id") == uid), {})
        roster_settings = own.get("settings") or {}
        budget = numeric((league.get("settings") or {}).get("waiver_budget"))
        used = numeric(roster_settings.get("waiver_budget_used"))
        total = numeric(matchup.get("custom_points"))
        if total is None:
            total = numeric(matchup.get("points"))
        weights = league.get("scoring_settings") or {}
        if not isinstance(weights, dict) or any(numeric(v) is None for v in weights.values()):
            raise ProviderError("Sleeper returned invalid scoring weights.")
        return {
            "id": internal_id,
            "external_id": league_id,
            "name": league.get("name") or "Sleeper league",
            "team_name": (manager.get("metadata") or {}).get("team_name")
            or user.get("display_name")
            or user.get("username")
            or "Your roster",
            "provider": "sleeper",
            "sport": "basketball",
            "is_demo": False,
            "season": league.get("season"),
            "standing": f"{len(rosters)} teams",
            "record": f"{roster_settings.get('wins', 0)}–{roster_settings.get('losses', 0)}",
            "faab_remaining": (
                max(0, budget - used) if budget is not None and used is not None else None
            ),
            "scoring": {"type": "points", "weights": weights},
            "rule_settings": league.get("settings") or {},
            "roster_positions": league.get("roster_positions") or [],
            "protections_reviewed": False,
            "rules": {},
            "period": period,
            "period_points": total,
            "points_warning": points_warning,
            "roster": [map_player(pid, True) for pid in own_ids],
            "other_rostered": [
                map_player(pid)
                for pid in sorted(
                    assigned
                    - set(own_ids)
                    - set(own.get("reserve") or [])
                    - set(own.get("taxi") or [])
                )
            ],
            "available": sorted(available, key=lambda p: p["name"]),
            "connection": {
                "username": user.get("username") or user.get("display_name"),
                "user_id": uid,
                "roster_id": own.get("roster_id"),
                "league_id": league_id,
            },
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "compatibility": view["compatibility"],
            "scouting_ready": False,
            "scouting_unavailable_reason": "Roster and period fantasy points are connected. Recent per-game statistics for unrostered players are not available from this connection; add a verified statistics feed before running recommendations. No model credits were used.",
            "notice": "Actual Sleeper NBA data retrieved by league ID. Fantasy points are Sleeper-reported scoring-period totals, not game averages or projections. Minutes, box scores and recent trends are unavailable. NBA compatibility is observed, not a documented discovery guarantee; unrostered status does not establish waiver eligibility.",
        }

    def snapshot(self):
        if not self.username or not self.league_id:
            raise ProviderError(
                "Provide a Sleeper username and NBA league ID for direct read-only import."
            )
        return self.connect(self.username, league_id=self.league_id)["snapshot"]
