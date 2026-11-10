"""Fits how absences count in game predictions (ABSENCE_WEIGHT and CUR_ROSTER_WEIGHT in app/model.py).

The problem: this season's team rating already reflects the games a player missed, and the model then takes his
whole value off again when he's marked out, so long absences were counted about twice.

A walk through every 2025-26 game, using only what was known before it:
- team rating = this season's net rating to date, weighted gp / (gp + 15) as in the model (no prior-season part);
- player impacts from the seasons before 2025-26 (same settings as the model, so out of sample);
- usual minutes and the rotation rule from the model, using minutes to date;
- who was out = players who had played for the team but didn't play that game (what a perfect injury report says).

Team net = w * rating to date
         + ABSENCE_WEIGHT * sum impact * (tonight's share - healthy share)        (players out tonight)
         + CUR_ROSTER_WEIGHT * w * sum impact * (healthy share - share to date)   (absences already in the rating)
The current model is ABSENCE_WEIGHT 1, CUR_ROSTER_WEIGHT 0.35 (ROSTER_WEIGHT applies to this season's part too).
Run from the project folder with the app's data:
  DATA_DIR="$HOME/Library/Application Support/NBA Stats" PYTHONPATH=. .venv/bin/python tools/fit_absences.py
"""
import math
from collections import defaultdict

import numpy as np

from app import model, nba, sync

SEASON = "2025-26"
BEFORE = ["2024-25", "2023-24", "2022-23"]   # impact evidence, newest first (decayed like the model)
MIN_GAMES = 5                                # start predicting once both teams have played this many


def impacts() -> dict[int, float]:
    """Net impact per 100 (off + def, scaled) from the seasons before SEASON, as model._build_impacts does."""
    acc, last_minutes = {}, {}
    for back, season in enumerate(BEFORE):
        weight = model.IMPACT_DECAY ** back
        per = {}
        for tid in sync.TEAM_IDS:
            f = nba.load(f"onoff_{tid}_{season}")
            if not f or f[0].empty:
                continue
            df = f[0]
            on, off = model._by_player(df[df.COURT_STATUS == "On"]), model._by_player(df[df.COURT_STATUS == "Off"])
            for pid in on.index.intersection(off.index):
                a, b = on.loc[pid], off.loc[pid]
                if a.MIN <= 0 or b.MIN <= 0:
                    continue
                s = per.setdefault(pid, [0.0, 0.0, 0.0, 0.0])
                s[0] += a.MIN; s[1] += b.MIN
                s[2] += a.MIN * (a.OFF_RATING - b.OFF_RATING); s[3] += a.MIN * (b.DEF_RATING - a.DEF_RATING)
        for pid, (on_min, off_min, o, d) in per.items():
            n = weight / (1 / on_min + 1 / off_min)
            s = acc.setdefault(pid, [0.0, 0.0, 0.0])
            s[0] += n; s[1] += n * o / on_min; s[2] += n * d / on_min
            if back == 0:
                last_minutes[pid] = on_min
    exp = {}
    for tid in sync.TEAM_IDS:
        f = nba.load(f"roster_{tid}_{SEASON}")
        for r in (f[0].itertuples() if f else []):
            exp[r.PLAYER_ID] = model._experience(getattr(r, "EXP", None))
    out = {}
    for pid in set(exp) | set(acc):
        n, o, d = acc.get(pid, (0.0, 0.0, 0.0))
        pl = model.Player(id=pid, name="", experience=exp.get(pid, 3))
        po, pd_ = model.IMPACT_PRIORS[model.League.impact_group(pl, last_minutes.get(pid, 0.0))]
        k = n / (n + model.IMPACT_HALF_TRUST)
        oo, dd = (o / n, d / n) if n else (0.0, 0.0)
        cap = model.IMPACT_CAP
        out[pid] = (max(-cap, min(cap, model.IMPACT_SCALE * (k * oo + (1 - k) * po)))
                    + max(-cap, min(cap, model.IMPACT_SCALE * (k * dd + (1 - k) * pd_))))
    return out


def rotation(mpg: dict[int, float]) -> dict[int, float]:
    """model.League.rotation for a {player: usual minutes} pool."""
    avail = sorted(mpg.items(), key=lambda x: -x[1])[:model.ROTATION_SIZE]
    total = sum(m for _, m in avail)
    if not total:
        return {}
    if total >= 240:
        mins, left = {}, 240.0
        for pid, m in avail:
            mins[pid] = min(m, left); left -= mins[pid]
        return {p: m for p, m in mins.items() if m >= 1}
    mins = {pid: m * 240 / total for pid, m in avail}
    for _ in range(5):
        excess = sum(m - model.MAX_MINUTES for m in mins.values() if m > model.MAX_MINUTES)
        if excess <= 0:
            break
        free = {p: m for p, m in mins.items() if m < model.MAX_MINUTES}
        ft = sum(free.values()) or 1
        mins = {p: min(m, model.MAX_MINUTES) + (excess * m / ft if p in free else 0) for p, m in mins.items()}
    return mins


def games() -> list[dict]:
    """Per game, per team: w, rating to date, the absence term and the already-in-the-rating term."""
    imp = impacts()
    t = model.League._team_games(model.League._load_logs(SEASON, "T"))
    p = model.League._load_logs(SEASON, "P")
    played = p[p["MIN"] > 0].groupby(["GAME_ID", "TEAM_ID"])["PLAYER_ID"].apply(set).to_dict()
    pmin = p.groupby(["GAME_ID", "PLAYER_ID"])["MIN"].sum().to_dict()
    team = defaultdict(lambda: {"gp": 0, "pts": 0.0, "opp": 0.0, "poss": 0.0})
    pl = defaultdict(lambda: {"min": 0.0, "gp": 0})      # (team, player) -> minutes and games to date
    current = {}                                         # player -> the team he last played for (traded players leave the pool)
    rows = []
    home = t[t["HOME"]]
    for day, day_games in home.groupby("GAME_DATE", sort=True):
        for g in day_games.itertuples():
            sides = []
            for tid in (g.TEAM_ID, g.OPP_ID):
                s = team[tid]
                if s["gp"] < MIN_GAMES:
                    break
                w = s["gp"] / (s["gp"] + model.CUR_HALF_GAMES)
                rating = 100 * (s["pts"] - s["opp"]) / s["poss"]
                pool = {pid: (v["min"] + 30) / (v["gp"] + 3) for (tm, pid), v in pl.items() if tm == tid and current.get(pid) == tid}
                healthy = rotation(pool)
                tonight_players = played.get((g.GAME_ID, tid), set())
                tonight = rotation({pid: m for pid, m in pool.items() if pid in tonight_players})
                out_term = sum(imp.get(pid, 0.0) * (tonight.get(pid, 0) - healthy.get(pid, 0)) / 48 for pid in set(healthy) | set(tonight))
                to_date = {pid: v["min"] / (s["gp"] * 48) for (tm, pid), v in pl.items() if tm == tid and current.get(pid) == tid}
                credit = w * sum(imp.get(pid, 0.0) * (healthy.get(pid, 0) / 48 - to_date.get(pid, 0)) for pid in set(healthy) | set(to_date))
                missing = sum(1 for pid, m in healthy.items() if pid not in tonight_players and m >= 15)
                sides.append((w * rating, out_term, credit, missing))
            if len(sides) == 2:
                rows.append({"margin": g.PTS - g.OPP_PTS, "home": sides[0], "away": sides[1]})
        # Then add the day's games to the running totals.
        for g in t[t["GAME_DATE"] == day].itertuples():
            s = team[g.TEAM_ID]
            s["gp"] += 1; s["pts"] += g.PTS; s["opp"] += g.OPP_PTS; s["poss"] += g.GAME_POSS
            for pid in played.get((g.GAME_ID, g.TEAM_ID), set()):
                v = pl[(g.TEAM_ID, pid)]
                v["min"] += pmin.get((g.GAME_ID, pid), 0.0); v["gp"] += 1
                current[pid] = g.TEAM_ID
    return rows


def main():
    rows = games()
    actual = np.array([r["margin"] for r in rows], float)
    H, A = np.array([r["home"] for r in rows], float), np.array([r["away"] for r in rows], float)
    absent = (H[:, 3] + A[:, 3]) > 0
    pace = 99.5

    def score(aw, cw, mask=None):
        net = lambda x: x[:, 0] + aw * x[:, 1] + cw * x[:, 2]
        m = pace * (net(H) - net(A)) / 100
        m = m + (actual - m).mean()           # home court fitted, the same for every setting
        m, act = (m, actual) if mask is None else (m[mask], actual[mask])
        p = 0.5 * (1 + np.vectorize(math.erf)(m / model.MARGIN_SD / math.sqrt(2)))
        won = act > 0
        return ((p - won) ** 2).mean(), ((m - act) ** 2).mean() ** 0.5, ((p >= 0.5) == won).mean()

    print(f"{len(rows)} games from {SEASON} ({absent.sum()} with a regular (15+ min) missing on either side)")
    print("                                  all games                     games with a regular out")
    for label, aw, cw in (("ignore absences", 0, 0), ("current model (1, 0.35)", 1, 0.35),
                          ("full credit (1, 1)", 1, 1)):
        a, b = score(aw, cw), score(aw, cw, absent)
        print(f"  {label:28} Brier {a[0]:.4f} RMSE {a[1]:.2f} win {a[2]:.1%}   Brier {b[0]:.4f} RMSE {b[1]:.2f} win {b[2]:.1%}")
    best = min(((score(aw, cw)[0], aw, cw) for aw in np.arange(0, 1.51, 0.05) for cw in np.arange(0, 1.51, 0.05)))
    a, b = score(best[1], best[2]), score(best[1], best[2], absent)
    print(f"  best: absence {best[1]:.2f}, credit {best[2]:.2f}  Brier {a[0]:.4f} RMSE {a[1]:.2f} win {a[2]:.1%}   Brier {b[0]:.4f} RMSE {b[1]:.2f} win {b[2]:.1%}")
    print("\nBrier by absence weight, with the best credit for each:")
    for aw in np.arange(0, 1.51, 0.25):
        bs = min((score(aw, cw)[0], cw) for cw in np.arange(0, 1.51, 0.05))
        print(f"  absence {aw:.2f}: credit {bs[1]:.2f} -> Brier {bs[0]:.4f}")
    print("\nFirst and second half of the season separately (stability):")
    half = np.arange(len(rows)) < len(rows) // 2
    for name, mask in (("first half", half), ("second half", ~half)):
        b = min(((score(aw, cw, mask)[0], aw, cw) for aw in np.arange(0, 1.51, 0.05) for cw in np.arange(0, 1.51, 0.05)))
        print(f"  {name}: best absence {b[1]:.2f}, credit {b[2]:.2f} (Brier {b[0]:.4f}); current {score(1, 0.35, mask)[0]:.4f}")


if __name__ == "__main__":
    main()
