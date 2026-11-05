import httpx
import json
import pytest
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.providers.sleeper import ProviderError, SleeperLeagueProvider


def test_sleeper_uses_only_documented_nfl_paths():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if "/user/" in request.url.path and "/leagues/" not in request.url.path:
            return httpx.Response(200, json={"user_id": "123", "display_name": "Scout"})
        return httpx.Response(200, json=[])

    p = SleeperLeagueProvider(httpx.Client(transport=httpx.MockTransport(handler)))
    result = p.connect("scout", 2026)
    p.connect("scout", 2026)
    assert result["basketball_supported"] is False
    assert paths == ["/v1/user/scout", "/v1/user/123/leagues/nfl/2026"]


@pytest.mark.parametrize(
    "status,data,match",
    [(200, None, "not found"), (429, {}, "rate limit"), (503, {}, "unavailable")],
)
def test_sleeper_errors(status, data, match):
    p = SleeperLeagueProvider(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(status, content=json.dumps(data))
            )
        )
    )
    with pytest.raises(ProviderError, match=match):
        p.connect("missing", 2026)


def test_sleeper_rejects_unsupported_sport():
    p = SleeperLeagueProvider(
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"sport": "mlb"}))
        )
    )
    with pytest.raises(ProviderError, match="sport"):
        p.league("123")


def test_scheduler_disabled_by_default(store):
    from backend.worker.scheduler import scheduled_scan, start_scheduler

    assert start_scheduler() is None
    assert scheduled_scan() is None


def test_cron_timezone_dst_and_idempotent_enqueue(store):
    from backend.worker.scan import enqueue

    tz = ZoneInfo("America/New_York")
    trigger = CronTrigger(hour=1, minute=30, timezone=tz)
    next_fire = trigger.get_next_fire_time(None, datetime(2026, 11, 1, 0, 0, tzinfo=tz))
    assert (
        next_fire.hour == 1
        and next_fire.minute == 30
        and str(next_fire.tzinfo) == "America/New_York"
    )
    first = enqueue("scheduled", source="schedule", request_key="nightly:2026-11-01", factory=store)
    assert (
        enqueue("scheduled", source="schedule", request_key="nightly:2026-11-01", factory=store)
        == first
    )
