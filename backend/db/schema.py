from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.database import Base


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid4().hex


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(primary_key=True, default="local")
    name: Mapped[str] = mapped_column(default="Courtside GM")


class League(Base):
    __tablename__ = "leagues"
    id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    provider: Mapped[str]
    is_demo: Mapped[bool] = mapped_column(Boolean)
    data: Mapped[dict] = mapped_column(JSON)


class Player(Base):
    __tablename__ = "players"
    id: Mapped[str] = mapped_column(primary_key=True)
    league_id: Mapped[str] = mapped_column(ForeignKey("leagues.id"), index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    data: Mapped[dict] = mapped_column(JSON)


class Workspace(Base):
    __tablename__ = "workspaces"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    active_league_id: Mapped[str] = mapped_column(ForeignKey("leagues.id"))


class RosterSnapshot(Base):
    __tablename__ = "roster_snapshots"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    league_id: Mapped[str] = mapped_column(ForeignKey("leagues.id"), index=True)
    captured_at: Mapped[str] = mapped_column(default=now)
    data: Mapped[dict] = mapped_column(JSON)


class Watchlist(Base):
    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_id", "player_id"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"))


class GuardrailSettings(Base):
    __tablename__ = "guardrail_settings"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class ScanRun(Base):
    __tablename__ = "scan_runs"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    league_id: Mapped[str] = mapped_column(ForeignKey("leagues.id"), index=True)
    instruction: Mapped[str] = mapped_column(Text)
    mode: Mapped[str]
    source: Mapped[str] = mapped_column(default="manual")
    stage: Mapped[str] = mapped_column(default="QUEUED", index=True)
    progress: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[str] = mapped_column(default=now)
    updated_at: Mapped[str] = mapped_column(default=now)
    lease_until: Mapped[float] = mapped_column(Float, default=0, index=True)
    worker_token: Mapped[str | None]
    attempts: Mapped[int] = mapped_column(default=0)
    live_calls: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    request_key: Mapped[str | None] = mapped_column(unique=True)


class ScanReview(Base):
    __tablename__ = "scan_reviews"
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), primary_key=True)
    signature: Mapped[str]


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    created_at: Mapped[str] = mapped_column(default=now)
    stage: Mapped[str]
    actor: Mapped[str]
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Clip(Base):
    __tablename__ = "clips"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"), index=True)
    content_hash: Mapped[str] = mapped_column(index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=now)


class SegmentationResult(Base):
    __tablename__ = "segmentation_results"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    cache_key: Mapped[str] = mapped_column(unique=True)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id"))
    model: Mapped[str]
    mode: Mapped[str]
    data: Mapped[dict] = mapped_column(JSON)


class PerceptionLog(Base):
    __tablename__ = "perception_logs"
    __table_args__ = (UniqueConstraint("scan_id", "player_id", "attempt"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"))
    attempt: Mapped[int]
    data: Mapped[dict] = mapped_column(JSON)


class CalculatedMetric(Base):
    __tablename__ = "calculated_metrics"
    __table_args__ = (UniqueConstraint("scan_id", "player_id", "name"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"))
    name: Mapped[str]
    data: Mapped[dict] = mapped_column(JSON)


class Verdict(Base):
    __tablename__ = "verdicts"
    __table_args__ = (UniqueConstraint("scan_id", "player_id"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"))
    data: Mapped[dict] = mapped_column(JSON)


class StagedMove(Base):
    __tablename__ = "staged_moves"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), unique=True)
    data: Mapped[dict] = mapped_column(JSON)


class ModelCache(Base):
    __tablename__ = "model_cache"
    key: Mapped[str] = mapped_column(primary_key=True)
    mode: Mapped[str]
    model: Mapped[str]
    data: Mapped[dict] = mapped_column(JSON)


class ModelCall(Base):
    __tablename__ = "model_calls"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    model: Mapped[str]
    operation: Mapped[str]
    status: Mapped[str]
    created_at: Mapped[str] = mapped_column(default=now)
    duration_ms: Mapped[int] = mapped_column(default=0)


class ScheduledInvocation(Base):
    __tablename__ = "scheduled_invocations"
    key: Mapped[str] = mapped_column(primary_key=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"))


class PlayerIdentity(Base):
    __tablename__ = "player_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_player_id"),
        Index("uq_identity_provider_sleeper", "provider", "sleeper_id", unique=True),
    )
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    sleeper_id: Mapped[str] = mapped_column(index=True)
    provider: Mapped[str] = mapped_column(index=True)
    provider_player_id: Mapped[str]
    data: Mapped[dict] = mapped_column(JSON)


class GameLog(Base):
    __tablename__ = "game_logs"
    __table_args__ = (UniqueConstraint("provider", "game_id", "provider_player_id"),)
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(index=True)
    game_id: Mapped[str]
    provider_player_id: Mapped[str] = mapped_column(index=True)
    data: Mapped[dict] = mapped_column(JSON)


class StatsRefresh(Base):
    __tablename__ = "stats_refreshes"
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    league_id: Mapped[str] = mapped_column(ForeignKey("leagues.id"), index=True)
    status: Mapped[str] = mapped_column(default="QUEUED", index=True)
    created_at: Mapped[str] = mapped_column(default=now)
    updated_at: Mapped[str] = mapped_column(default=now)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    data: Mapped[dict] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
