"""Keeps the local cache up to date, in a background thread so pages never wait on stats.nba.com.

The previous season is downloaded once. Current-season data (schedule, results, rosters,
on/off splits) is re-downloaded when it's older than config.REFRESH_HOURS, and also soon after
each regular-season game should have finished (see results_due), so results and the predictions
for the next games catch up within the hour.
"""

import threading
from datetime import timedelta
import traceback
from datetime import datetime

import pandas as pd
from nba_api.stats.static import teams as static_teams

from . import config, nba

TEAM_IDS = sorted(t["id"] for t in static_teams.get_teams())

_lock = threading.Lock()
_state = {"running": False, "done": 0, "total": 0, "error": None, "finished_at": None, "generation": 0}


def history_seasons() -> list[str]:
    """Finished seasons with matchup tracking: from 2017-18 to last season."""
    first, prev = int(nba.FIRST_MATCHUP_SEASON[:4]), int(config.previous_season()[:4])
    return [config.season_label(y) for y in range(first, prev + 1)]


def _older_impact_seasons() -> list[str]:
    from .model import IMPACT_SEASONS
    start = int(config.previous_season()[:4])
    return [config.season_label(start - back) for back in range(1, IMPACT_SEASONS - 1)]


def _jobs(force: bool):
    cur, prev = config.current_season(), config.previous_season()
    fresh = 0 if force else config.REFRESH_HOURS
    jobs = [
        lambda: nba.game_logs(prev, "P", None),
        lambda: nba.game_logs(prev, "T", None),
        lambda: nba.player_advanced(prev, None),
        lambda: nba.shot_zones(prev, None),
        *[(lambda t=t: nba.on_off(t, prev, None)) for t in TEAM_IDS],
        *[(lambda s=s: nba.matchups(s, None)) for s in history_seasons()],
        # Older on/off splits for player impact (model.IMPACT_SEASONS), downloaded once.
        *[(lambda t=t, s=s: nba.on_off(t, s, None)) for s in _older_impact_seasons() for t in TEAM_IDS],
        lambda: nba.closest_defender(prev, None),
        lambda: nba.closest_defender(prev, None, "3 Pointers"),
        lambda: nba.schedule(cur, fresh),
        lambda: nba.game_logs(cur, "P", fresh),
        lambda: nba.game_logs(cur, "T", fresh),
        *[(lambda t=t: nba.roster(t, cur, fresh)) for t in TEAM_IDS],
    ]
    # Season-level splits only exist once the season has started.
    started = [
        lambda: nba.player_advanced(cur, fresh),
        lambda: nba.shot_zones(cur, fresh),
        *[(lambda t=t: nba.on_off(t, cur, fresh)) for t in TEAM_IDS],
        lambda: nba.matchups(cur, fresh),
        lambda: nba.closest_defender(cur, fresh),
        lambda: nba.closest_defender(cur, fresh, "3 Pointers"),
    ]
    return jobs, started


def _run(force: bool):
    try:
        jobs, started = _jobs(force)
        _state["total"] = len(jobs)
        for job in jobs:
            job()
            _state["done"] += 1
        if len(nba.game_logs(config.current_season(), "T", None)):
            _state["total"] += len(started)
            for job in started:
                job()
                _state["done"] += 1
        _state["error"] = None
    except Exception as exc:
        traceback.print_exc()
        _state["error"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        _state["finished_at"] = datetime.now(config.TZ)
        _state["generation"] += 1
        _state["running"] = False


def needs_refresh() -> bool:
    cur, prev = config.current_season(), config.previous_season()
    # Data added in later versions of the app (matchup history, defense) is fetched on the next refresh.
    needed = [f"matchups_{s}" for s in history_seasons()] + [f"defend_{prev}", f"defend3_{prev}"] \
        + [f"onoff_{t}_{s}" for s in _older_impact_seasons() for t in TEAM_IDS]
    if not all(nba.cached_at(k) for k in needed):
        return True
    return not nba.is_fresh(f"gamelog_T_{cur}", config.REFRESH_HOURS) or not nba.is_fresh(f"schedule_{cur}", config.REFRESH_HOURS)


GAME_HOURS = 3          # a game is usually over this long after tip-off
RESULTS_RETRY_MINUTES = 30
RESULTS_LOOKBACK_DAYS = 2   # stop waiting on a game this old (postponed, or never logged)


def results_due() -> bool:
    """A regular-season game should be over by now but isn't in the downloaded results yet.
    Checked at most every RESULTS_RETRY_MINUTES, since stats.nba.com can take a while to post a game."""
    cur = config.current_season()
    fetched = nba.cached_at(f"gamelog_T_{cur}")
    schedule, logs = nba.load(f"schedule_{cur}"), nba.load(f"gamelog_T_{cur}")
    if fetched is None or not schedule or logs is None:
        return False
    now = pd.Timestamp.now(tz="UTC")
    if now - fetched < timedelta(minutes=RESULTS_RETRY_MINUTES):
        return False
    games = schedule[0]
    start = pd.to_datetime(games["gameDateTimeUTC"], utc=True, errors="coerce")
    over = (games["gameId"].str[:3] == "002") & (start + timedelta(hours=GAME_HOURS) <= now) \
        & (start > now - timedelta(days=RESULTS_LOOKBACK_DAYS))
    logged = set(logs[0]["GAME_ID"]) if len(logs[0]) else set()
    return bool((over & ~games["gameId"].isin(logged)).any())


def start(force: bool = False) -> None:
    """Start a background refresh if one isn't already running and the data is stale, a game's
    results are due, or force (the Refresh button)."""
    with _lock:
        if _state["running"]:
            return
        due = results_due()
        if not (force or due or needs_refresh()):
            return
        # A failed sync waits a few minutes before trying again automatically.
        if not force and _state["error"] and _state["finished_at"] and (datetime.now(config.TZ) - _state["finished_at"]).total_seconds() < 300:
            return
        _state.update(running=True, done=0, total=0)
        # Results due: re-download this season's data even though it isn't REFRESH_HOURS old yet.
        threading.Thread(target=_run, args=(force or due,), daemon=True).start()


def has_core_data() -> bool:
    cur, prev = config.current_season(), config.previous_season()
    keys = [f"gamelog_P_{prev}", f"gamelog_T_{prev}", f"schedule_{cur}", f"advanced_{prev}", f"shotzones_{prev}"]
    keys += [f"roster_{t}_{cur}" for t in TEAM_IDS] + [f"onoff_{t}_{prev}" for t in TEAM_IDS]
    return all(nba.cached_at(k) for k in keys)


def status() -> dict:
    cur = config.current_season()
    last = nba.cached_at(f"gamelog_T_{cur}")
    return {
        **_state,
        "last_synced": last.astimezone(config.TZ) if last else None,
    }


if __name__ == "__main__":
    # `python -m app.sync` forces a full refresh of current-season data from the terminal.
    _state["running"] = True
    _run(force=True)
    print(status())
