"""Supported data sources; public status exposes presence, never credentials."""

from backend.config import settings
from backend.providers.stats_balldontlie import BallDontLieStatsProvider, StatsProviderError
from backend.providers.stats_sportradar import SportradarStatsProvider


def configured(name):
    secret = {
        "balldontlie": settings.balldontlie_api_key,
        "sportradar": settings.sportradar_api_key,
    }.get(name)
    return bool(secret and secret.get_secret_value())


def build_provider(name, **kwargs):
    if name == "sportradar":
        return SportradarStatsProvider(**kwargs)
    if name == "balldontlie":
        return BallDontLieStatsProvider()
    raise StatsProviderError(
        "Choose a supported statistics provider or import a licensed normalized JSON batch."
    )
