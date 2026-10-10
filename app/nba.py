"""stats.nba.com client: every response is cached on disk as JSON, so each request is made once.

stats.nba.com throttles or blocks clients that send many requests quickly, so requests are
spaced out and retried with a backoff.
"""

import json
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

import pandas as pd
from nba_api.stats import endpoints as E

from . import config

_MIN_GAP = 0.7  # seconds between requests
_lock = threading.Lock()
_last_request = 0.0


def _path(key: str):
    return config.CACHE_DIR / f"{key}.json"


def cached_at(key: str) -> datetime | None:
    path = _path(key)
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def is_fresh(key: str, max_age_hours: float | None) -> bool:
    """max_age_hours=None means the cached copy never expires (e.g. a finished season)."""
    fetched = cached_at(key)
    if fetched is None:
        return False
    if max_age_hours is None:
        return True
    return (datetime.now(timezone.utc) - fetched).total_seconds() < max_age_hours * 3600


def load(key: str) -> list[pd.DataFrame] | None:
    path = _path(key)
    if not path.exists():
        return None
    frames = json.loads(path.read_text())
    return [pd.DataFrame(f["data"], columns=f["columns"]) for f in frames]


def fetch(key: str, request: Callable[[], list[pd.DataFrame]], max_age_hours: float | None) -> list[pd.DataFrame]:
    """Return the cached frames for `key`, downloading them first if missing or stale."""
    if is_fresh(key, max_age_hours):
        return load(key)
    global _last_request
    error = None
    for attempt in range(3):
        with _lock:
            wait = _MIN_GAP - (time.monotonic() - _last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                frames = request()
                error = None
            except Exception as exc:  # timeouts, connection resets, bad JSON when throttled
                error = exc
            finally:
                _last_request = time.monotonic()
        if error is None:
            break
        time.sleep(3 * (attempt + 1))
    if error is not None:
        if (stale := load(key)) is not None:
            return stale
        raise error
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = [json.loads(f.to_json(orient="split", index=False)) for f in frames]
    tmp = _path(key).with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(_path(key))
    return frames


# --- Endpoints ----------------------------------------------------------------

_T = 60  # request timeout, seconds


def schedule(season: str, max_age) -> pd.DataFrame:
    return fetch(f"schedule_{season}", lambda: E.ScheduleLeagueV2(season=season, timeout=_T).get_data_frames()[:1], max_age)[0]


def game_logs(season: str, kind: str, max_age) -> pd.DataFrame:
    """Every regular-season game line for the season; kind is "P" (players) or "T" (teams)."""
    return fetch(
        f"gamelog_{kind}_{season}",
        lambda: E.LeagueGameLog(player_or_team_abbreviation=kind, season=season, timeout=_T).get_data_frames()[:1],
        max_age,
    )[0]


def roster(team_id: int, season: str, max_age) -> pd.DataFrame:
    return fetch(
        f"roster_{team_id}_{season}",
        lambda: E.CommonTeamRoster(team_id=team_id, season=season, timeout=_T).get_data_frames()[:1],
        max_age,
    )[0]


def on_off(team_id: int, season: str, max_age) -> pd.DataFrame:
    """One row per player and court status ("On"/"Off") with the team's ratings in those minutes."""
    def request():
        frames = E.TeamPlayerOnOffSummary(team_id=team_id, season=season, timeout=_T).get_data_frames()
        return [pd.concat(frames[1:3], ignore_index=True)]
    return fetch(f"onoff_{team_id}_{season}", request, max_age)[0]


def player_advanced(season: str, max_age) -> pd.DataFrame:
    return fetch(
        f"advanced_{season}",
        lambda: E.LeagueDashPlayerStats(
            season=season, measure_type_detailed_defense="Advanced", timeout=_T
        ).get_data_frames()[:1],
        max_age,
    )[0]


def shot_zones(season: str, max_age) -> pd.DataFrame:
    """Shots by court zone for every player, with columns like "Mid-Range FGA"."""
    def request():
        df = E.LeagueDashPlayerShotLocations(season=season, distance_range="By Zone", timeout=_T).get_data_frames()[0]
        df.columns = [b if not a else f"{a} {b}" for a, b in df.columns]
        return [df]
    return fetch(f"shotzones_{season}", request, max_age)[0]


def player_info(player_id: int) -> pd.DataFrame:
    return fetch(
        f"playerinfo_{player_id}",
        lambda: E.CommonPlayerInfo(player_id=player_id, timeout=_T).get_data_frames()[:1],
        24 * 7,
    )[0]


def career(player_id: int) -> list[pd.DataFrame]:
    """[regular season by season, playoffs by season] per game, one row per team in traded seasons."""
    def request():
        frames = E.PlayerCareerStats(player_id=player_id, per_mode36="PerGame", timeout=_T).get_data_frames()
        return [frames[0], frames[2]]
    return fetch(f"career_{player_id}", request, 24)
