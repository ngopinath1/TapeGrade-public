from copy import deepcopy

from sqlalchemy import select

from backend.api.types import Guardrails
from backend.db.database import session_scope
from backend.db.schema import GuardrailSettings, League, Player, RosterSnapshot, User, Workspace
from backend.providers.demo import DemoLeagueProvider
from backend.providers.base import ScoringEngine


def apply_scoring(snapshot, guards):
    league = deepcopy(snapshot)
    weights = (guards or {}).get("scoring_weights")
    if weights is not None and weights != league.get("scoring", {}).get("weights"):
        league["scoring"] = {**league.get("scoring", {}), "weights": weights}
        if league.get("is_demo", True):
            for player in league["roster"] + league["available"]:
                player["fantasy_points"] = ScoringEngine().score(player["stats"], weights)
                # The sample has no per-game box scores to recalculate its synthetic trend.
                player["trend"] = []
    return league


def seed_demo(factory=None):
    with session_scope(factory) as s:
        if s.get(User, "local") is None:
            s.add(User(id="local"))
            s.flush()
        if s.get(GuardrailSettings, "local") is None:
            s.add(GuardrailSettings(user_id="local", data=Guardrails().model_dump()))
        if s.get(League, "demo-nba") is None:
            data = DemoLeagueProvider().snapshot()
            s.add(League(id="demo-nba", user_id="local", provider="demo", is_demo=True, data=data))
            s.flush()
            for p in data["roster"] + data["available"]:
                s.add(Player(id=p["id"], league_id="demo-nba", is_demo=True, data=p))
            s.add(RosterSnapshot(league_id="demo-nba", data={"roster": data["roster"]}))
            s.flush()
        if s.get(Workspace, "local") is None:
            s.add(Workspace(user_id="local", active_league_id="demo-nba"))


def get_league(factory=None, league_id=None):
    with session_scope(factory) as s:
        workspace = s.get(Workspace, "local")
        snapshot = s.get(
            League, league_id or (workspace.active_league_id if workspace else "demo-nba")
        ).data
        guards = (
            s.get(GuardrailSettings, "local").data
            if snapshot.get("is_demo", True)
            else snapshot.get("guardrails")
        )
    from backend.services.stat_enrichment import enrich_snapshot

    return enrich_snapshot(apply_scoring(snapshot, guards), factory)


def get_guardrails(factory=None, league_id=None):
    league = get_league(factory, league_id)
    with session_scope(factory) as s:
        if not league.get("is_demo", True):
            return Guardrails.model_validate(
                league.get("guardrails") or Guardrails(protected_players=[]).model_dump()
            )
        return Guardrails.model_validate(s.get(GuardrailSettings, "local").data)


def save_league(snapshot, factory=None, select_workspace=True):
    """Persist a provider snapshot; background refreshes preserve the active workspace."""
    with session_scope(factory) as s:
        row = s.get(League, snapshot["id"])
        data = dict(snapshot)
        if row:
            from backend.services.stat_enrichment import fingerprint

            guards = row.data.get("guardrails")
            if fingerprint(apply_scoring(row.data, guards)) == fingerprint(
                apply_scoring(data, guards)
            ):
                data["rules"] = row.data.get("rules", {})
            data["eligibility_reviews"] = row.data.get("eligibility_reviews", {})
            data["protections_reviewed"] = bool(row.data.get("protections_reviewed")) and {
                p["id"] for p in row.data["roster"]
            } == {p["id"] for p in data["roster"]}
        if row and row.data.get("guardrails"):
            guards = dict(row.data["guardrails"])
            current = {p["id"] for p in snapshot["roster"]}
            guards["protected_players"] = [
                pid for pid in guards["protected_players"] if pid in current
            ]
            data["guardrails"] = guards
        if row:
            row.data = data
        else:
            row = League(
                id=data["id"], user_id="local", provider=data["provider"], is_demo=False, data=data
            )
            s.add(row)
            s.flush()
        for p in data["roster"] + data["available"]:
            existing = s.get(Player, p["id"])
            if existing:
                existing.data = p
            else:
                s.add(Player(id=p["id"], league_id=data["id"], is_demo=False, data=p))
        s.add(
            RosterSnapshot(
                league_id=data["id"],
                data={"roster": data["roster"], "period": data.get("period"), "source": "Sleeper"},
            )
        )
        if select_workspace:
            s.get(Workspace, "local").active_league_id = data["id"]
    return data


def select_demo(factory=None):
    with session_scope(factory) as s:
        s.get(Workspace, "local").active_league_id = "demo-nba"
