"""Timezone helpers shared by the web notebook and Telegram bot."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Jakarta"
ALIASES = {
    "WIB": "Asia/Jakarta",
    "WITA": "Asia/Makassar",
    "WIT": "Asia/Jayapura",
    "UTC": "UTC",
}

# Curated choices keep onboarding simple; any valid IANA zone is also accepted
# by the Telegram command and API.
COMMON_TIMEZONES = (
    ("Asia/Jakarta", "WIB (Jakarta)"),
    ("Asia/Makassar", "WITA (Makassar)"),
    ("Asia/Jayapura", "WIT (Jayapura)"),
    ("Asia/Singapore", "Singapore"),
    ("Asia/Bangkok", "Bangkok"),
    ("UTC", "UTC"),
    ("Europe/London", "London"),
    ("America/New_York", "New York"),
    ("America/Los_Angeles", "Los Angeles"),
)


def resolve_timezone(value):
    """Return a canonical IANA zone, or None for an invalid/empty value."""
    raw = str(value or "").strip()
    if not raw:
        return None
    canonical = ALIASES.get(raw.upper(), raw)
    try:
        ZoneInfo(canonical)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return canonical


def local_now(zone_name=DEFAULT_TIMEZONE):
    """Current wall time as a naive datetime in the chosen book timezone."""
    zone = ZoneInfo(resolve_timezone(zone_name) or DEFAULT_TIMEZONE)
    return datetime.now(zone).replace(tzinfo=None)


def zone_label(zone_name=DEFAULT_TIMEZONE, at=None):
    """A compact, current label such as WIB / UTC+07:00."""
    canonical = resolve_timezone(zone_name) or DEFAULT_TIMEZONE
    zone = ZoneInfo(canonical)
    aware = (at or datetime.now(zone)).replace(tzinfo=zone) if (at is None or at.tzinfo is None) else at.astimezone(zone)
    offset = aware.strftime("%z")
    offset = "UTC%s%s:%s" % (offset[:3], offset[3:5], offset[5:]) if offset else "UTC"
    short = aware.tzname() or canonical
    return "%s (%s)" % (short, offset)


def choices():
    return COMMON_TIMEZONES


def due_in_timezone(fire_text, now_utc, timezone_value):
    """Compare a stored wall-clock fire time with an aware UTC clock."""
    from datetime import timezone
    zone = ZoneInfo(resolve_timezone(timezone_value) or DEFAULT_TIMEZONE)
    try:
        fire = datetime.fromisoformat(str(fire_text))
    except (TypeError, ValueError):
        return False
    if fire.tzinfo is None:
        fire = fire.replace(tzinfo=zone)
    return fire.astimezone(timezone.utc) <= now_utc.astimezone(timezone.utc)


def reminder_identity(fire_text, timezone_value):
    """Stable dedup key retaining the stored fire stamp.

    Naive values remain compatible with existing sent markers; aware values
    retain their offset so equal wall times in separate zones do not collide.
    """
    try:
        stamp = datetime.fromisoformat(str(fire_text))
    except (TypeError, ValueError):
        return str(fire_text)
    if stamp.tzinfo is None:
        # Exact legacy string preserves markers, including fractional seconds.
        return str(fire_text)
    return stamp.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S")


def local_timestamp(now_utc, timezone_value):
    zone = ZoneInfo(resolve_timezone(timezone_value) or DEFAULT_TIMEZONE)
    return now_utc.astimezone(zone).replace(tzinfo=None)


def local_to_utc(stamp, timezone_value):
    """Convert legacy local wall time to UTC while honoring DST folds/gaps."""
    zone = ZoneInfo(resolve_timezone(timezone_value) or DEFAULT_TIMEZONE)
    if stamp.tzinfo is not None:
        return stamp.astimezone(ZoneInfo("UTC"))
    return stamp.replace(tzinfo=zone).astimezone(ZoneInfo("UTC"))


def main():
    import sys
    for raw in sys.argv[1:]:
        print("%s -> %s" % (raw, resolve_timezone(raw)))


if __name__ == "__main__":
    main()
