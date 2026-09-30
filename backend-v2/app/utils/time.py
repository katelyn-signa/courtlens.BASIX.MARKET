from datetime import datetime, timezone


def utcnow() -> datetime:
    """UTC-aware 'now'. All persisted timestamps are UTC-aware."""
    return datetime.now(timezone.utc)
