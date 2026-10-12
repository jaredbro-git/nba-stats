"""Prediction tracker: saves each game's prediction before tip-off and scores it once the game is final.

While the app is open, every game starting within LOG_AHEAD_HOURS gets a prediction, refreshed on
each update until the game starts, so the saved one is the last made before tip-off. Games the app
wasn't open for beforehand are left out (shown as "not tracked"), never predicted after the fact,
with one exception: preseason games already played when the tracker was added are "backfilled" with
a prediction made afterwards, which is fair only because no regular-season games had been added to
the model's data since. They're labelled and can be left out of the scores.

Predictions use the saved list of unavailable players at the time, like the rest of the app.
Stored in predictions.json in the data folder.
"""

import json
import threading
import time
from datetime import datetime, timedelta, timezone

from . import config

LOG_AHEAD_HOURS = 48
MIN_INTERVAL = 600          # seconds between updates triggered by page loads
KINDS = {"001": "pre", "002": "reg", "004": "post", "005": "post", "006": "post"}
KIND_LABELS = {"reg": "Regular season", "pre": "Preseason", "post": "Playoffs"}
CALIBRATION_BINS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]

_lock = threading.Lock()
_last_update = 0.0


def _file():
    return config.DATA_DIR / "predictions.json"


def load() -> dict[str, dict]:
    try:
        return json.loads(_file().read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _save(records: dict[str, dict]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(records, indent=1, sort_keys=True))
    tmp.replace(_file())


def update(lg, out: set[int], force: bool = False) -> None:
    """Log predictions for games starting soon and record results for finished ones."""
    global _last_update
    if not force and time.time() - _last_update < MIN_INTERVAL:
        return
    if not _lock.acquire(blocking=False):
        return
    try:
        _last_update = time.time()
        games = getattr(lg, "all_games", None)
        if games is None or games.empty:
            return
        records = load()
        now = datetime.now(timezone.utc)
        # Backfilling preseason is only fair while no regular-season game is in the model's data.
        season_started = any(ts.gp for ts in lg.team_seasons[lg.cur].values())
        changed = False
        for g in games.itertuples():
            kind = KINDS.get(g.gameId[:3])
            home, away = g.homeTeam_teamId, g.awayTeam_teamId
            if kind is None or home not in lg.teams or away not in lg.teams:
                continue
            start = g.start.to_pydatetime().astimezone(timezone.utc)
            rec = records.get(g.gameId)
            upcoming = g.gameStatus == 1 and now < start <= now + timedelta(hours=LOG_AHEAD_HOURS)
            backfill = g.gameStatus == 3 and rec is None and kind == "pre" and not season_started
            if upcoming or backfill:
                p = lg.predict(home, away, out & _rosters(lg, home, away), g.us_date, bool(g.isNeutral))
                rec = {
                    "game_id": g.gameId, "kind": kind, "start": start.isoformat(), "home": int(home), "away": int(away),
                    "home_pts": round(p["home"]["pts"], 1), "away_pts": round(p["away"]["pts"], 1),
                    "home_win": round(p["home_win"], 4), "logged_at": now.isoformat(), "backfilled": backfill,
                    "out": sorted(out & _rosters(lg, home, away)),
                }
                records[g.gameId] = rec
                changed = True
            if rec and g.gameStatus == 3 and "result" not in rec:
                rec["result"] = {"home": int(g.homeTeam_score), "away": int(g.awayTeam_score)}
                changed = True
        if changed:
            _save(records)
    finally:
        _lock.release()


def _rosters(lg, *team_ids) -> set[int]:
    return {p.id for p in lg.players.values() if p.team_id in team_ids}


def summary(records: list[dict]) -> dict:
    """Accuracy for finished games: winners picked, margin and total errors, Brier score, calibration."""
    done = [r for r in records if "result" in r]
    if not done:
        return {"games": 0}
    correct = margin_err = total_err = brier = 0.0
    bins = [{"lo": lo, "hi": hi, "games": 0, "won": 0, "expected": 0.0} for lo, hi in CALIBRATION_BINS]
    for r in done:
        actual_margin = r["result"]["home"] - r["result"]["away"]
        pred_margin = r["home_pts"] - r["away_pts"]
        home_won = actual_margin > 0
        correct += (r["home_win"] >= 0.5) == home_won
        margin_err += abs(pred_margin - actual_margin)
        total_err += abs((r["home_pts"] + r["away_pts"]) - (r["result"]["home"] + r["result"]["away"]))
        brier += (r["home_win"] - home_won) ** 2
        fav_prob = max(r["home_win"], 1 - r["home_win"])
        fav_won = home_won if r["home_win"] >= 0.5 else not home_won
        for b in bins:
            if b["lo"] <= fav_prob < b["hi"]:
                b["games"] += 1
                b["won"] += fav_won
                b["expected"] += fav_prob
    n = len(done)
    for b in bins:
        b["rate"] = b["won"] / b["games"] if b["games"] else None
        b["expected"] = b["expected"] / b["games"] if b["games"] else None
    return {"games": n, "accuracy": correct / n, "margin_error": margin_err / n, "total_error": total_err / n,
            "brier": brier / n, "bins": bins}


def rows(records: list[dict], lg) -> list[dict]:
    """Records ready for the page, newest first, with names and how each prediction did."""
    out = []
    for r in records:
        row = dict(r)
        row["start_local"] = datetime.fromisoformat(r["start"]).astimezone(config.TZ)
        row["home_team"], row["away_team"] = lg.teams.get(r["home"]), lg.teams.get(r["away"])
        if "result" in r:
            actual = r["result"]["home"] - r["result"]["away"]
            row["correct"] = (r["home_win"] >= 0.5) == (actual > 0)
            row["margin_error"] = (r["home_pts"] - r["away_pts"]) - actual
        out.append(row)
    return sorted(out, key=lambda r: r["start"], reverse=True)
