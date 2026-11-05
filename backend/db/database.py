from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import ROOT, settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    if url.startswith("sqlite:///./"):
        url = "sqlite:///" + str(ROOT / url.removeprefix("sqlite:///./"))
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")

    return engine


settings.data_dir.mkdir(exist_ok=True)
engine = make_engine(settings.database_url)
Session = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope(factory=None):
    with (factory or Session)() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def initialize(engine_override=None):
    from backend.db import schema  # noqa: F401

    target = engine_override or engine
    legacy_reviews = (
        "scan_runs" in inspect(target).get_table_names()
        and "scan_reviews" not in inspect(target).get_table_names()
    )
    Base.metadata.create_all(target)
    if legacy_reviews:
        # Existing reports predate review tracking; avoid presenting the entire archive as new.
        with sessionmaker(target)() as session:
            for run in session.scalars(
                select(schema.ScanRun).where(schema.ScanRun.stage.in_(("COMPLETED", "FAILED")))
            ):
                session.add(
                    schema.ScanReview(scan_id=run.id, signature=f"{run.attempts}:{run.stage}")
                )
            session.commit()
    # Additive index for installations that created identity tables before this index.
    for index in schema.PlayerIdentity.__table__.indexes:
        index.create(engine_override or engine, checkfirst=True)
