"""Provider-neutral per-game observations. Missing is never a measured zero."""

from datetime import date
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, model_validator

Count = Annotated[int, Field(strict=True, ge=0, le=300)]


class BoxScore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pts: Count | None = None
    reb: Count | None = None
    ast: Count | None = None
    stl: Count | None = None
    blk: Count | None = None
    to: Count | None = None
    tpm: Count | None = None
    tpa: Count | None = None
    fgm: Count | None = None
    fga: Count | None = None
    ftm: Count | None = None
    fta: Count | None = None
    oreb: Count | None = None
    dreb: Count | None = None
    pf: Count | None = None
    tf: Count | None = None
    ff: Count | None = None

    @model_validator(mode="after")
    def consistent(self):
        for made, attempted in [("fgm", "fga"), ("ftm", "fta"), ("tpm", "tpa")]:
            a, b = getattr(self, made), getattr(self, attempted)
            if a is not None and b is not None and a > b:
                raise ValueError("Made shots exceed attempts.")
        if all(getattr(self, k) is not None for k in ("reb", "oreb", "dreb")):
            if self.reb != self.oreb + self.dreb:
                raise ValueError("Rebounds do not reconcile.")
        return self


class Athlete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=2, max_length=150)
    team: str | None = None
    nba_id: str | None = None
    sportradar_id: str | None = Field(
        None, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    birth_date: date | None = None
    jersey: str | None = None


class GameRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,40}$")
    athlete_id: str = Field(min_length=1, max_length=100)
    game_id: str = Field(min_length=1, max_length=100)
    game_date: date
    season: int = Field(ge=1946, le=2200, description="NBA season starting year")
    season_type: Literal["regular", "playoffs", "preseason", "playin", "ist"] = "regular"
    status: Literal["final", "in_progress", "scheduled", "postponed"]
    participation: Literal["played", "dnp", "unknown"]
    minutes: float | None = Field(None, ge=0, le=100, allow_inf_nan=False, strict=True)
    stats: BoxScore
    fetched_at: AwareDatetime
    source_ref: str = Field(min_length=1, max_length=1000)
    synthetic: bool = Field(False, strict=True)
    quality_notes: list[str] = Field(default_factory=list, max_length=20)

    @property
    def coverage(self):
        return sorted(self.stats.model_dump(exclude_none=True))


class StatsBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,40}$")
    start_date: date
    end_date: date
    fetched_at: AwareDatetime
    complete: bool = Field(strict=True)
    source_ref: str = Field(min_length=1, max_length=1000)
    athletes: list[Athlete] = Field(max_length=2000)
    games: list[GameRecord] = Field(max_length=15000)
    synthetic: bool = Field(strict=True)
    request_count: int = Field(0, ge=0)
    cache_hits: int = Field(0, ge=0)

    @model_validator(mode="after")
    def coherent(self):
        if not 0 <= (self.end_date - self.start_date).days <= 29:
            raise ValueError("Import window must cover at most 30 days.")
        ids = [p.id for p in self.athletes]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate athlete IDs.")
        known = set(ids)
        for game in self.games:
            if game.provider != self.provider or game.athlete_id not in known:
                raise ValueError("Game provider/athlete does not match the batch.")
            if not self.start_date <= game.game_date <= self.end_date:
                raise ValueError("Game outside the declared window.")
            if game.synthetic != self.synthetic:
                raise ValueError("Mixed synthetic and real observations are forbidden.")
            if game.fetched_at > self.fetched_at:
                raise ValueError("Game fetched after its batch.")
        return self


class StatsProvider(Protocol):
    def fetch(self, start: date, end: date, season: int) -> StatsBatch: ...
