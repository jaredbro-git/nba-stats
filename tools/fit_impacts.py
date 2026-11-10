"""Fits the player-impact settings in app/model.py (IMPACT_PRIORS, IMPACT_HALF_TRUST, IMPACT_DECAY, IMPACT_SEASONS).

Out of sample: predicts each player's on/off split in 2023-24, 2024-25 and 2025-26 from the seasons before it
plus his experience, and keeps the settings with the least error (weighted by each target's evidence).
Run from the project folder with the app's data:
  DATA_DIR="$HOME/Library/Application Support/NBA Stats" PYTHONPATH=. .venv/bin/python tools/fit_impacts.py
Needs on/off splits and rosters back to 2021-22 in the cache.
"""
import itertools
import numpy as np
import pandas as pd
from app import model, nba, sync
SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]

def season_onoff(season):
    acc = {}
    for tid in sync.TEAM_IDS:
        f = nba.load(f"onoff_{tid}_{season}")
        if not f or f[0].empty: continue
        df = f[0]
        on, off = model._by_player(df[df.COURT_STATUS == "On"]), model._by_player(df[df.COURT_STATUS == "Off"])
        for pid in on.index.intersection(off.index):
            a, b = on.loc[pid], off.loc[pid]
            if a.MIN <= 0 or b.MIN <= 0: continue
            s = acc.setdefault(pid, [0.0, 0.0, 0.0, 0.0, 0.0])  # weight, off*w, def*w, on_min, off_min
            s[0] += a.MIN; s[1] += a.MIN * (a.OFF_RATING - b.OFF_RATING); s[2] += a.MIN * (b.DEF_RATING - a.DEF_RATING)
            s[3] += a.MIN; s[4] += b.MIN
    rows = [(pid, o / w, d / w, 1 / (1 / on_ + 1 / off_), on_) for pid, (w, o, d, on_, off_) in acc.items()]
    return pd.DataFrame(rows, columns=["pid", "off", "def", "n", "on_min"]).set_index("pid")

def experience(season):
    exp = {}
    for tid in sync.TEAM_IDS:
        f = nba.load(f"roster_{tid}_{season}")
        if not f: continue
        for r in f[0].itertuples():
            e = str(r.EXP).strip()
            exp[r.PLAYER_ID] = 0 if e in ("R", "", "nan") else int(float(e))
    return exp

data, exps = {}, {}


def main():
    global data, exps
    data = {s: season_onoff(s) for s in SEASONS}
    exps = {s: experience(s) for s in SEASONS}
    print({s: len(d) for s, d in data.items()})

    def bucket(e): return 0 if e == 0 else 1 if e == 1 else 2 if e == 2 else 3 if e <= 5 else 4
    BUCKETS = ["rookie", "2nd season", "3rd season", "4th-6th", "7th+"]

    def history(target_idx, decay, max_back):
        """Decayed history before the target season: raw off/def and evidence n."""
        acc = {}
        for back in range(1, max_back + 1):
            i = target_idx - back
            if i < 0: break
            w = decay ** (back - 1)
            for pid, r in data[SEASONS[i]].iterrows():
                s = acc.setdefault(pid, [0.0, 0.0, 0.0])
                s[0] += w * r.n; s[1] += w * r.n * r.off; s[2] += w * r.n * r["def"]
        return {pid: (o / n, d / n, n) for pid, (n, o, d) in acc.items() if n > 0}

    def evaluate(decay, max_back, n0, with_prior, targets=(2, 3, 4)):
        """Returns weighted MSE (off+def) and fitted prior means by experience bucket."""
        rows = []
        for t in targets:
            hist = history(t, decay, max_back)
            exp = exps[SEASONS[t]]
            for pid, r in data[SEASONS[t]].iterrows():
                if r.n < 100: continue  # target too noisy to score against
                ho, hd, hn = hist.get(pid, (0.0, 0.0, 0.0))
                k = hn / (hn + n0)
                rows.append((bucket(exp.get(pid, 3)), k, ho, hd, r.off, r["def"], r.n))
        d = pd.DataFrame(rows, columns=["b", "k", "ho", "hd", "to", "td", "w"])
        mu = {}
        for side, h, tcol in (("off", "ho", "to"), ("def", "hd", "td")):
            for b in range(5):
                g = d[d.b == b]
                if not with_prior or g.empty: mu[(side, b)] = 0.0; continue
                x = 1 - g.k; y = g[tcol] - g.k * g[h]
                mu[(side, b)] = float((g.w * x * y).sum() / (g.w * x * x).sum())
        pred_o = d.k * d.ho + (1 - d.k) * d.b.map(lambda b: mu[("off", b)])
        pred_d = d.k * d.hd + (1 - d.k) * d.b.map(lambda b: mu[("def", b)])
        mse = ((d.w * ((pred_o - d.to) ** 2 + (pred_d - d.td) ** 2)).sum() / d.w.sum())
        return mse, mu, len(d)

    base_mse, _, n = evaluate(0.6, 1, 375, False)
    print(f"\nNow: 1 earlier season, half-trust at 375 min, prior 0 -> error {base_mse:.2f} ({n} player-seasons)")
    best = None
    for decay, max_back, n0, prior in itertools.product([0.4, 0.6, 0.8], [1, 2, 3], [150, 250, 375, 600, 900, 1400], [False, True]):
        mse, mu, _ = evaluate(decay, max_back, n0, prior)
        if best is None or mse < best[0]: best = (mse, decay, max_back, n0, prior, mu)
    mse, decay, max_back, n0, prior, mu = best
    print(f"Best: decay {decay}, {max_back} earlier seasons, half-trust at {n0} min, prior by experience {prior} -> error {mse:.2f} ({100 * (1 - mse / base_mse):.1f}% better)")
    for b in range(5): print(f"  prior {BUCKETS[b]:11}: off {mu[('off', b)]:+.2f}  def {mu[('def', b)]:+.2f}  net {mu[('off', b)] + mu[('def', b)]:+.2f} per 100")
    mse_np, _, _ = evaluate(decay, max_back, n0, False)
    print(f"Same but prior 0 for everyone -> error {mse_np:.2f}")

    print("\nWider search, with a 'fringe veteran' group (3+ seasons, under 600 on-court minutes the season before):")
    BUCKETS = ["rookie", "2nd season", "3rd season", "fringe vet", "regular vet"]
    def bucket2(e, last_min): return 0 if e == 0 else 1 if e == 1 else 2 if e == 2 else 3 if last_min < 600 else 4
    def evaluate2(decay, max_back, n0, targets=(2, 3, 4)):
        rows = []
        for t in targets:
            hist = history(t, decay, max_back); exp = exps[SEASONS[t]]; last = data[SEASONS[t - 1]]
            for pid, r in data[SEASONS[t]].iterrows():
                if r.n < 100: continue
                ho, hd, hn = hist.get(pid, (0.0, 0.0, 0.0))
                k = hn / (hn + n0)
                last_min = last.on_min.get(pid, 0.0)
                rows.append((bucket2(exp.get(pid, 3), last_min), k, ho, hd, r.off, r["def"], r.n))
        d = pd.DataFrame(rows, columns=["b", "k", "ho", "hd", "to", "td", "w"])
        mu = {}
        for side, h, tcol in (("off", "ho", "to"), ("def", "hd", "td")):
            for b in range(5):
                g = d[d.b == b]
                x = 1 - g.k; y = g[tcol] - g.k * g[h]
                mu[(side, b)] = float((g.w * x * y).sum() / (g.w * x * x).sum()) if len(g) else 0.0
        pred_o = d.k * d.ho + (1 - d.k) * d.b.map(lambda b: mu[("off", b)])
        pred_d = d.k * d.hd + (1 - d.k) * d.b.map(lambda b: mu[("def", b)])
        return ((d.w * ((pred_o - d.to) ** 2 + (pred_d - d.td) ** 2)).sum() / d.w.sum()), mu, d.b.value_counts().sort_index().to_dict()
    best = None
    for decay, max_back, n0 in itertools.product([0.5, 0.6, 0.7, 0.8], [2, 3, 4], [1000, 1400, 2000, 2800, 4000, 6000]):
        mse, mu, counts = evaluate2(decay, max_back, n0)
        if best is None or mse < best[0]: best = (mse, decay, max_back, n0, mu, counts)
    mse, decay, max_back, n0, mu, counts = best
    print(f"Best: decay {decay}, {max_back} earlier seasons, half-trust at {n0} min -> error {mse:.2f} ({100 * (1 - mse / base_mse):.1f}% better than now)")
    for b in range(5): print(f"  prior {BUCKETS[b]:11}: off {mu[('off', b)]:+.2f}  def {mu[('def', b)]:+.2f}  net {mu[('off', b)] + mu[('def', b)]:+.2f}  (n={counts.get(b, 0)})")
    for n0_ in (1000, 1400, 2000, 2800, 4000):
        print(f"  half-trust {n0_}: error {evaluate2(decay, max_back, n0_)[0]:.2f}")


if __name__ == "__main__":
    main()
