"""Re-checks IMPACT_SCALE in app/model.py: 2025-26 teams' real with/without net rating for regulars who missed
5+ games, against the unscaled impact estimate (old rule vs new). Run like tools/fit_impacts.py."""
import numpy as np
import pandas as pd
from app import nba, sync, model
from fit_impacts import experience, season_onoff
SEASONS = ["2022-23", "2023-24", "2024-25", "2025-26"]
data = {s: season_onoff(s) for s in SEASONS}
exp = experience("2025-26")

def estimate(new):
    """Unscaled net impact per player as of the end of 2025-26."""
    out = {}
    if new:
        acc = {}
        for back, s in enumerate(reversed(SEASONS)):
            w = model.IMPACT_DECAY ** back
            for pid, r in data[s].iterrows():
                a = acc.setdefault(pid, [0.0, 0.0, 0.0]); a[0] += w * r.n; a[1] += w * r.n * r.off; a[2] += w * r.n * r["def"]
        last = data["2024-25"].on_min
        for pid, (n, o, d) in acc.items():
            e = exp.get(pid, 3)
            g = "rookie" if e == 0 else "second season" if e == 1 else "third season" if e == 2 else ("fringe veteran" if last.get(pid, 0) < model.FRINGE_MINUTES else "regular veteran")
            po, pd_ = model.IMPACT_PRIORS[g]; k = n / (n + model.IMPACT_HALF_TRUST)
            out[pid] = k * (o / n) + (1 - k) * po + k * (d / n) + (1 - k) * pd_
    else:  # the old rule: this season + last at 0.6, half trust at 375 minutes, prior 0
        acc = {}
        for s, w in (("2025-26", 1.0), ("2024-25", 0.6)):
            for pid, r in data[s].iterrows():
                a = acc.setdefault(pid, [0.0, 0.0, 0.0, 0.0])
                a[0] += w * r.on_min; a[1] += w * r.on_min * (r.off + r["def"]); a[2] += w * r.on_min; a[3] += w * r.on_min / max(r.on_min / r.n - 1, 1e-6)
        for pid, (w, x, on_, off_) in acc.items():
            n = 1 / (1 / on_ + 1 / max(off_, 1e-6)); k = n / (n + 375)
            out[pid] = k * x / w
    return out

# Real with/without splits in 2025-26.
p = nba.load("gamelog_P_2025-26")[0]; t = nba.load("gamelog_T_2025-26")[0]
t["POSS"] = t.FGA - t.OREB + t.TOV + 0.44 * t.FTA
opp = t[["GAME_ID", "TEAM_ID", "PTS", "POSS"]].rename(columns={"TEAM_ID": "OPP_ID", "PTS": "OPP_PTS", "POSS": "OPP_POSS"})
t = t.merge(opp, on="GAME_ID"); t = t[t.TEAM_ID != t.OPP_ID]
rows = []
for (pid, tid), mine in p.groupby(["PLAYER_ID", "TEAM_ID"]):
    mpg = mine.MIN.astype(float).mean()
    if mpg < 20 or len(mine) < 20: continue
    games = t[(t.TEAM_ID == tid) & t.GAME_DATE.between(mine.GAME_DATE.min(), mine.GAME_DATE.max())]
    played = games.GAME_ID.isin(set(mine.GAME_ID))
    if (~played).sum() < 5: continue
    net = lambda g: 100 * (g.PTS.sum() - g.OPP_PTS.sum()) / ((g.POSS.sum() + g.OPP_POSS.sum()) / 2)
    rows.append((pid, mpg, net(games[played]) - net(games[~played]), (~played).sum()))
d = pd.DataFrame(rows, columns=["pid", "mpg", "actual", "missed"])
print(len(d), "regulars who missed 5+ games")
for name, new in (("old", False), ("new", True)):
    est = estimate(new)
    d[name] = d.pid.map(est).fillna(0) * d.mpg / 48
    w = d.missed
    slope = (w * d[name] * d.actual).sum() / (w * d[name] ** 2).sum()
    corr = np.corrcoef(d[name], d.actual)[0, 1]
    print(f"{name}: real splits move {slope:.2f}x the unscaled estimate, correlation {corr:.2f}")
