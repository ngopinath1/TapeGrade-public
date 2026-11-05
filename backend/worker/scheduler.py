from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.config import settings
from backend.services.state import get_guardrails, get_league

TZ = ZoneInfo("America/New_York")


def scheduled_scan(slot="nightly"):
    """Reusable entry point for a future Modal cron. Date/slot key prevents DST duplicates."""
    from backend.worker.scan import enqueue

    guardrails = get_guardrails()
    if not settings.scheduler_enabled or not guardrails.schedule_enabled:
        return None
    league = get_league()
    if not league.get("is_demo", True) and not league.get("scouting_ready", False):
        return None
    key = f"{league['id']}:{slot}:{datetime.now(TZ).date().isoformat()}"
    return enqueue(
        "Find the best opportunity for my roster before waivers.",
        source="schedule",
        request_key=key,
    )


def start_scheduler():
    if not settings.scheduler_enabled:
        return None
    scheduler = BackgroundScheduler(timezone=TZ)
    scheduler.add_job(
        scheduled_scan,
        CronTrigger(hour=1, minute=30, timezone=TZ),
        id="nightly",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    # Poll the setting at the top of each hour, so changing it takes effect without a restart.
    def pre_waiver():
        hour = get_guardrails().pre_waiver_hour
        if hour is not None and datetime.now(TZ).hour == hour:
            scheduled_scan("pre-waiver")

    scheduler.add_job(
        pre_waiver,
        CronTrigger(minute=0, timezone=TZ),
        id="pre-waiver",
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    return scheduler
