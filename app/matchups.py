"""Player-vs-defender matchups: head-to-head history, expected outcomes for any pair, and how changing
who guards whom moves a prediction.

The NBA tracks every shooter-defender pair (whole seasons from 2017-18): possessions guarded, points,
shots. Each older season counts PREV_WEIGHT times as much as the one after it. From that:
  - a shooter's baseline: points, shots and shooting per possession against everyone who guarded him;
  - a defender's rating: points per possession allowed compared with what those shooters usually
    score. It leans on FG% allowed as the closest defender at the shot (CLOSE_WEIGHT, this season and
    last), because matchup points charge help defenders when the man they left scores; the matchup
    part is compared within position (guards, wings, bigs) for the same reason;
  - a size effect: how FG% moves with the height difference beyond the defender's own ability,
    fitted from all pairs with known heights and converted to points;
  - for a pair: the defender's rating plus the size effect, adjusted by their head-to-head record,
    more as that record grows.
A primary defender guards about PRIMARY_SHARE of a player's possessions. When the user picks a
different defender, the shooter's points change by that share times the difference in effects, and
PASS_THROUGH of the change reaches the team score (teammates pick up the rest). The likely matchups
are already part of the team ratings, so they add nothing on their own.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config, nba

PREV_WEIGHT = 0.6      # each older season counts 60% as much as the one after it
DEF_SHRINK = 400       # possessions of evidence before a defender's matchup rating is taken at half weight
PAIR_SHRINK = 150      # the same for one shooter-defender pair
CLOSE_SHRINK = 300     # shots defended before closest-defender FG% is taken at half weight
CLOSE_WEIGHT = 0.7     # the defender rating leans on closest-defender FG%, which isn't fooled by help defense
FG_SHRINK = 40         # shots before a pair's own FG% is taken at half weight
THREE_SHRINK = 30      # the same for threes
PRIMARY_SHARE = 0.4    # share of a player's possessions his primary defender guards
PASS_THROUGH = 0.6     # share of a shooter's points change that reaches the team score
PTS_PER_MAKE = 2.25    # converts FG% allowed into points
SHOOTERS_PER_TEAM = 5
POSITION_GROUP = {"G": "guard", "G-F": "guard", "F-G": "wing", "F": "wing", "F-C": "big", "C-F": "big", "C": "big"}

COLS = ["PARTIAL_POSS", "PLAYER_PTS", "MATCHUP_FGM", "MATCHUP_FGA", "MATCHUP_FG3M", "MATCHUP_FG3A",
        "MATCHUP_AST", "MATCHUP_TOV", "MATCHUP_FTA", "GP"]


@dataclass
class Pair:
    poss: float          # weighted possessions
    effect: float        # points per possession vs the shooter's baseline (shrunk)


def _weights(seasons: list[str]) -> dict[str, float]:
    """Newest season 1, each older one PREV_WEIGHT times the next."""
    return {s: PREV_WEIGHT ** i for i, s in enumerate(sorted(seasons, reverse=True))}


def _slope(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    if len(x) < 50 or w.sum() == 0:
        return 0.0
    xm, ym = np.average(x, weights=w), np.average(y, weights=w)
    var = np.sum(w * (x - xm) ** 2)
    return float(np.sum(w * (x - xm) * (y - ym)) / var) if var else 0.0


class Matchups:
    def __init__(self, seasons: list[str], positions: dict[int, str], heights: dict[int, float]):
        self.heights = heights
        frames = []
        for season in seasons:
            loaded = nba.load(f"matchups_{season}")
            if loaded and len(loaded[0]):
                frames.append(loaded[0][["OFF_PLAYER_ID", "DEF_PLAYER_ID", *COLS]].assign(SEASON=season))
        self.empty = not frames
        self.first_season = min((f["SEASON"].iat[0] for f in frames), default=None)
        self.pairs: dict[tuple[int, int], Pair] = {}
        self.by_shooter: dict[int, list[int]] = {}
        self.by_defender: dict[int, list[int]] = {}
        self.rate: dict[int, float] = {}
        self.defender: dict[int, float] = {}
        self.defender_poss: dict[int, float] = {}
        self.defender_fg: dict[int, float] = {}
        self.defender_fg3: dict[int, float] = {}
        self.size_pts = self.size_fg = 0.0
        if self.empty:
            return
        df = pd.concat(frames, ignore_index=True)
        df["W"] = df["SEASON"].map(_weights(list(df["SEASON"].unique()))).astype("float32")
        df["POSS_W"] = df["PARTIAL_POSS"] * df["W"]
        df["PTS_W"] = df["PLAYER_PTS"] * df["W"]
        df["FGM_W"], df["FGA_W"] = df["MATCHUP_FGM"] * df["W"], df["MATCHUP_FGA"] * df["W"]
        df["FG3M_W"], df["FG3A_W"] = df["MATCHUP_FG3M"] * df["W"], df["MATCHUP_FG3A"] * df["W"]

        # Shooter baselines: weighted totals against everyone who guarded him.
        rate_cols = {"FGA": "MATCHUP_FGA", "FG3A": "MATCHUP_FG3A", "FTA": "MATCHUP_FTA", "TOV": "MATCHUP_TOV", "AST": "MATCHUP_AST"}
        for k, c in rate_cols.items():
            df[f"{k}_RW"] = df[c] * df["W"]
        shooter = df.groupby("OFF_PLAYER_ID")[["POSS_W", "PTS_W", "FGM_W", "FGA_W", "FG3M_W", "FG3A_W",
                                               *[f"{k}_RW" for k in rate_cols]]].sum()
        valid = shooter["POSS_W"] > 0
        self.rate = (shooter["PTS_W"] / shooter["POSS_W"])[valid].to_dict()
        self.league_fg = df["MATCHUP_FGM"].sum() / max(1, df["MATCHUP_FGA"].sum())
        self.league_fg3 = df["MATCHUP_FG3M"].sum() / max(1, df["MATCHUP_FG3A"].sum())
        self.base_fg = ((shooter["FGM_W"] + 100 * self.league_fg) / (shooter["FGA_W"] + 100)).to_dict()
        self.base_fg3 = ((shooter["FG3M_W"] + 150 * self.league_fg3) / (shooter["FG3A_W"] + 150)).to_dict()
        self.per_poss = {k: (shooter[f"{k}_RW"] / shooter["POSS_W"])[valid].to_dict() for k in rate_cols}
        self.shooter_poss = shooter["POSS_W"].to_dict()
        df["DIFF"] = df["PTS_W"] - df["POSS_W"] * df["OFF_PLAYER_ID"].map(self.rate).fillna(0)

        # Defender rating: matchup points compared within position, blended with closest-defender FG%.
        d = df.groupby("DEF_PLAYER_ID")[["DIFF", "POSS_W"]].sum()
        by_matchup = d["DIFF"] / (d["POSS_W"] + DEF_SHRINK)
        self.defender_poss = d["POSS_W"].to_dict()
        group = by_matchup.index.map(lambda pid: POSITION_GROUP.get(positions.get(pid, ""), "other"))
        for g in set(group):
            mask = group == g
            if d["POSS_W"][mask].sum() > 0:
                by_matchup[mask] -= np.average(by_matchup[mask], weights=d["POSS_W"][mask])
        fga_per_poss = df["MATCHUP_FGA"].sum() / df["PARTIAL_POSS"].sum()
        self.defender_fg = self._closest("defend")
        self.defender_fg3 = self._closest("defend3")
        by_close = pd.Series(self.defender_fg, dtype=float) * PTS_PER_MAKE * fga_per_poss
        ids = by_matchup.index.union(by_close.index)
        self.defender = ((1 - CLOSE_WEIGHT) * by_matchup.reindex(ids).fillna(0)
                         + CLOSE_WEIGHT * by_close.reindex(ids).fillna(0)).to_dict()

        # Pairs.
        pair = df.groupby(["OFF_PLAYER_ID", "DEF_PLAYER_ID"]).agg(
            POSS_W=("POSS_W", "sum"), DIFF=("DIFF", "sum"), FGM_W=("FGM_W", "sum"), FGA_W=("FGA_W", "sum")).reset_index()

        # Size: how FG% moves with the defender's height advantage (inches) beyond the defender's own
        # closest-defender FG%, fitted from pairs where both heights are known. It's turned into points
        # rather than fitted on points, because matchup points carry the help-defense bias (bigs are
        # charged on switches and for the men they leave), which made taller defenders look worse.
        gap = pair["DEF_PLAYER_ID"].map(heights) - pair["OFF_PLAYER_ID"].map(heights)
        rating = pair["DEF_PLAYER_ID"].map(self.defender).fillna(0)
        fg_known = gap.notna() & (pair["FGA_W"] >= 5)
        close_fg = pair["DEF_PLAYER_ID"].map(self.defender_fg).fillna(0)
        y_fg = (pair["FGM_W"] / pair["FGA_W"] - pair["OFF_PLAYER_ID"].map(self.base_fg) - close_fg)[fg_known]
        self.size_fg = float(np.clip(_slope(gap[fg_known].to_numpy(float), y_fg.to_numpy(float),
                                            pair.loc[fg_known, "FGA_W"].to_numpy(float)), -0.01, 0.01))
        self.size_pts = self.size_fg * PTS_PER_MAKE * fga_per_poss

        prior = rating + self.size_pts * gap.fillna(0)
        pair["EFFECT"] = (pair["DIFF"] + PAIR_SHRINK * prior) / (pair["POSS_W"] + PAIR_SHRINK)
        for o, dd, poss, effect in zip(pair["OFF_PLAYER_ID"], pair["DEF_PLAYER_ID"], pair["POSS_W"], pair["EFFECT"]):
            self.pairs[(o, dd)] = Pair(poss, effect)
            self.by_shooter.setdefault(o, []).append(dd)
            self.by_defender.setdefault(dd, []).append(o)
        self._pair_w = pair.set_index(["OFF_PLAYER_ID", "DEF_PLAYER_ID"]).sort_index()
        self._rows = df[["OFF_PLAYER_ID", "DEF_PLAYER_ID", "SEASON", *COLS]].set_index(
            ["OFF_PLAYER_ID", "DEF_PLAYER_ID"]).sort_index()

    @staticmethod
    def _closest(key: str) -> dict[int, float]:
        """FG% allowed as the closest defender minus those shooters' usual FG%, shrunk (this season and last)."""
        parts = []
        for season, weight in ((config.current_season(), 1.0), (config.previous_season(), PREV_WEIGHT)):
            loaded = nba.load(f"{key}_{season}")
            if loaded and len(loaded[0]):
                c = loaded[0].copy()
                c["DIFF_FGM"] = (c["D_FG_PCT"] - c["NORMAL_FG_PCT"]) * c["D_FGA"] * weight
                c["FGA_W"] = c["D_FGA"] * weight
                parts.append(c)
        if not parts:
            return {}
        c = pd.concat(parts).groupby("CLOSE_DEF_PERSON_ID")[["DIFF_FGM", "FGA_W"]].sum()
        return (c["DIFF_FGM"] / (c["FGA_W"] + CLOSE_SHRINK)).to_dict()

    # --- Lookups --------------------------------------------------------------------

    def _size(self, shooter: int, defender: int) -> float | None:
        hs, hd = self.heights.get(shooter), self.heights.get(defender)
        return hd - hs if hs and hd else None

    def effect(self, shooter: int, defender: int | None) -> float:
        """Points per possession the defender takes off (negative) or adds to the shooter's baseline."""
        if not defender:
            return 0.0
        pair = self.pairs.get((shooter, defender))
        if pair:
            return pair.effect
        return self.defender.get(defender, 0.0) + self.size_pts * (self._size(shooter, defender) or 0.0)

    def possessions(self, shooter: int, defender: int) -> float:
        """Unweighted possessions over every tracked season (0 if they've never met)."""
        if (shooter, defender) not in self.pairs:
            return 0.0
        return float(self._rows.loc[[(shooter, defender)], "PARTIAL_POSS"].sum())

    def likely_defender(self, shooter: int, candidates: list[int]) -> int | None:
        """The candidate who has guarded this shooter for the most (weighted) possessions."""
        best, best_poss = None, 0.0
        for d in candidates:
            pair = self.pairs.get((shooter, d))
            if pair and pair.poss > best_poss:
                best, best_poss = d, pair.poss
        return best

    def points_change(self, shooter: int, base_pts: float, defender: int | None, baseline_defender: int | None) -> float:
        rate = self.rate.get(shooter)
        if not rate:
            return 0.0
        return base_pts * PRIMARY_SHARE * (self.effect(shooter, defender) - self.effect(shooter, baseline_defender)) / rate

    def seasons(self, shooter: int, defender: int) -> list[dict]:
        """Head-to-head totals for each season, newest first."""
        if (shooter, defender) not in self.pairs:
            return []
        rows = self._rows.loc[[(shooter, defender)]]
        return [{"season": r.SEASON, **{c: getattr(r, c) for c in COLS}}
                for r in rows.sort_values("SEASON", ascending=False).itertuples()]

    def history(self, shooter: int, defender: int | None) -> dict | None:
        """Head-to-head totals over every tracked season, or None if they've never matched up."""
        seasons = self.seasons(shooter, defender) if defender else []
        return {c: sum(s[c] for s in seasons) for c in COLS} if seasons else None

    def top_for_shooter(self, shooter: int, n: int = 10) -> list[int]:
        return sorted(self.by_shooter.get(shooter, []), key=lambda d: -self.pairs[(shooter, d)].poss)[:n]

    def top_for_defender(self, defender: int, n: int = 10) -> list[int]:
        return sorted(self.by_defender.get(defender, []), key=lambda s: -self.pairs[(s, defender)].poss)[:n]

    # --- Expected outcome for any pair ----------------------------------------------

    def estimate(self, shooter: int, defender: int) -> dict | None:
        """Expected scoring and shooting per 100 possessions when `defender` guards `shooter`, with the
        factors behind it. Works for pairs that have never met (ratings and size only)."""
        rate = self.rate.get(shooter)
        if rate is None:
            return None
        size = self._size(shooter, defender)
        rating = self.defender.get(defender, 0.0)
        size_pts = self.size_pts * (size or 0.0)
        pair = self.pairs.get((shooter, defender))
        w = self._pair_w.loc[(shooter, defender)] if pair else None
        poss = float(w["POSS_W"]) if pair else 0.0
        effect = pair.effect if pair else rating + size_pts

        base_fg = self.base_fg.get(shooter, self.league_fg)
        fg_prior = self.defender_fg.get(defender, 0.0) + self.size_fg * (size or 0.0)
        if pair and float(w["FGA_W"]):
            fga_w = float(w["FGA_W"])
            fg_dev = ((float(w["FGM_W"]) - fga_w * base_fg) + FG_SHRINK * fg_prior) / (fga_w + FG_SHRINK)
        else:
            fg_dev = fg_prior

        base_fg3 = self.base_fg3.get(shooter, self.league_fg3)
        fg3_prior = self.defender_fg3.get(defender, 0.0)
        hist = self.history(shooter, defender)
        if hist and hist["MATCHUP_FG3A"]:
            fg3_dev = ((hist["MATCHUP_FG3M"] - hist["MATCHUP_FG3A"] * base_fg3) + THREE_SHRINK * fg3_prior) / (hist["MATCHUP_FG3A"] + THREE_SHRINK)
        else:
            fg3_dev = fg3_prior

        per100 = {k: 100 * v.get(shooter, 0.0) for k, v in self.per_poss.items()}
        return {
            "pts100": 100 * (rate + effect), "base_pts100": 100 * rate, "effect100": 100 * effect,
            "fg": base_fg + fg_dev, "base_fg": base_fg, "fg3": base_fg3 + fg3_dev, "base_fg3": base_fg3,
            "fga100": per100["FGA"], "fg3a100": per100["FG3A"], "fta100": per100["FTA"],
            "tov100": per100["TOV"], "ast100": per100["AST"],
            "rating100": 100 * rating, "close_fg": self.defender_fg.get(defender), "close_fg3": self.defender_fg3.get(defender),
            "size": size, "size_pts100": 100 * size_pts, "size_fg": self.size_fg * (size or 0.0),
            "h2h100": 100 * float(w["DIFF"]) / poss if pair and poss else None,
            "h2h_weight": poss / (poss + PAIR_SHRINK),
            "confidence": "None" if not pair else "Low" if poss < 50 else "Medium" if poss < 150 else "High",
        }


_cache: dict = {"sig": None, "value": None}


def load(lg) -> Matchups:
    """Matchups for every tracked season, rebuilt when a matchup or defense file changes."""
    first, cur = int(nba.FIRST_MATCHUP_SEASON[:4]), int(config.current_season()[:4])
    seasons = [config.season_label(y) for y in range(first, cur + 1)]
    names = [f"matchups_{s}" for s in seasons] + [f"defend{k}_{s}" for k in ("", "3") for s in (lg.cur, lg.prev)]
    sig = tuple(nba.cached_at(n) for n in names)
    if _cache["sig"] != sig:
        positions = {p.id: p.position for p in lg.players.values()}
        heights = {p.id: p.height for p in lg.players.values() if p.height}
        _cache["value"] = Matchups(seasons, positions, heights)
        _cache["sig"] = sig
    return _cache["value"]
