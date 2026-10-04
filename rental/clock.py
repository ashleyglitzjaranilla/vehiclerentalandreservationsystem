"""The one place the business timezone is defined.

The system operates in a single timezone: Philippine time. A customer entering
9am means 9am, an admin reads 9am, and "today" means today in Manila. Every
datetime is stored naive and compared naive, so nothing converts anywhere.

Phase 1 left three clocks in play -- an aware UTC `utcnow()`, the naive value it
became once stored, and the server's own local date for "today". Subtracting one
from another raises TypeError, and "today's pickups" was the server's day rather
than the business's.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

# A fixed offset rather than ZoneInfo("Asia/Manila"): the Philippines has not
# observed DST since 1978, so the offset is exact, and this needs no tz database
# to be present in the serverless runtime.
PH = timezone(timedelta(hours=8))


def now() -> datetime:
    """The current local time, naive, for storage and comparison.

    Deliberately not `datetime.now()`: that returns the *server's* local time,
    which is Manila in development and UTC on Vercel -- the kind of divergence
    that hides a bug until deploy.
    """
    return datetime.now(PH).replace(tzinfo=None)


def today() -> date:
    """The current local date. This is what "today's pickups" means."""
    return now().date()
