import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
# The Mac app keeps data in ~/Library/Application Support/NBA Stats (set by desktop.py).
DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR / "data")
CACHE_DIR = DATA_DIR / "cache"
UNAVAILABLE_FILE = DATA_DIR / "unavailable.json"

# Game times are shown in this timezone.
TZ = ZoneInfo(os.getenv("TIMEZONE", "Pacific/Auckland"))
US_TZ = ZoneInfo("America/New_York")

# The app and ./run.sh both serve on this port, so only one can run at a time.
PORT = 8001

# Current-season data (results, rosters, schedule) is re-downloaded when older than this.
REFRESH_HOURS = 6


def season_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def _current_start_year(today: date) -> int:
    # A new season's schedule and rosters are published over the northern summer;
    # from August on, "current" means the season that starts that October.
    return today.year if today.month >= 8 else today.year - 1


def current_season() -> str:
    return season_label(_current_start_year(datetime.now(US_TZ).date()))


def previous_season() -> str:
    return season_label(_current_start_year(datetime.now(US_TZ).date()) - 1)
