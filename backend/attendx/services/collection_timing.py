"""V2 collection timing shared by the offline laptop and central ingestion."""

from datetime import datetime, time, timedelta

COLLECTION_SECONDS = 300
START_GRACE_SECONDS = 300


def class_bounds(local: datetime, start: str | None, end: str | None):
    """Return local wall-clock class bounds; malformed/overnight slots fail closed."""
    if not start or not end:
        return None
    try:
        begins = datetime.combine(local.date(), time.fromisoformat(start))
        ends = datetime.combine(local.date(), time.fromisoformat(end))
    except ValueError:
        return None
    return (begins, ends) if begins < ends else None


def collection_start_allowed(local: datetime, start: str | None, end: str | None) -> bool:
    bounds = class_bounds(local, start, end)
    return bool(
        bounds and bounds[0] <= local.replace(tzinfo=None) <= bounds[1] + timedelta(seconds=START_GRACE_SECONDS)
    )
