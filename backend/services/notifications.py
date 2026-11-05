import logging


def notify(scan_id: str, result: dict) -> None:
    """Extension point for opt-in email/Telegram; local-only in v1."""
    logging.getLogger("tapegrade.notifications").info(
        "Scan %s completed; recommendation ready=%s", scan_id, bool(result["staged_move"])
    )
