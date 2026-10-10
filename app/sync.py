"""Keeps the local cache up to date, in a background thread so pages never wait on stats.nba.com.

The previous season is downloaded once. Current-season data (schedule, results, rosters,
on/off splits) is re-downloaded when it's older than config.REFRESH_HOURS.
"""

import threading
import traceback
from datetime import datetime

from nba_api.stats.static import teams as static_teams

from . import config, nba

TEAM_IDS = sorted(t["id"] for t in static_teams.get_teams())

_lock = threading.Lock()
_state = {"running": False, "done": 0, "total": 0, "error": None, "finished_at": None, "generation": 0}


def _jobs(force: bool):
    cur, prev = config.current_season(), config.previous_season()
    fresh = 0 if force else config.REFRESH_HOURS
    jobs = [
        lambda: nba.game_logs(prev, "P", None),
        lambda: nba.game_logs(prev, "T", None),
        lambda: nba.player_advanced(prev, None),
        lambda: nba.shot_zones(prev, None),
        *[(lambda t=t: nba.on_off(t, prev, None)) for t in TEAM_IDS],
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
    cur = config.current_season()
    return not nba.is_fresh(f"gamelog_T_{cur}", config.REFRESH_HOURS) or not nba.is_fresh(f"schedule_{cur}", config.REFRESH_HOURS)


def start(force: bool = False) -> None:
    """Start a background refresh if one isn't already running and the data is stale (or force)."""
    with _lock:
        if _state["running"] or not (force or needs_refresh()):
            return
        # A failed sync waits a few minutes before trying again automatically.
        if not force and _state["error"] and _state["finished_at"] and (datetime.now(config.TZ) - _state["finished_at"]).total_seconds() < 300:
            return
        _state.update(running=True, done=0, total=0)
        threading.Thread(target=_run, args=(force,), daemon=True).start()


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
