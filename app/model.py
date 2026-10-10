"""The expected-results model, built from the cached data.

How a matchup is predicted (each step is shown on the game page):
  1. Team ratings: points scored and allowed per 100 possessions, and pace. Last season's
     ratings are pulled 25% toward league average (teams regress year to year) and blended with
     this season's, which take over as games are played (half weight after 15 games).
  2. Player impact: how a team's ratings change when the player is on vs off the court,
     shrunk heavily toward zero because these splits are noisy.
  3. Lineup adjustment: each team's rating moves by impact × (change in the player's share of
     minutes) compared with the season the rating came from. That covers offseason moves,
     returning players and players marked unavailable (their minutes go to teammates).
  4. Score: pace × each offence against the other defence, plus home court and back-to-backs.
  5. Player lines: expected minutes × per-minute rates, scaled so they add up to the team score.
"""

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
from nba_api.stats.static import teams as static_teams

from . import config, nba

EAST = {"ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DET", "IND", "MIA", "MIL", "NYK", "ORL", "PHI", "TOR", "WAS"}
STATS = ["PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV"]
# Stats that scale with the team's predicted scoring; the rest scale with pace.
SCORING_STATS = {"PTS", "AST", "FG3M"}

PREV_WEIGHT = 0.6        # last season's games count 60% as much as this season's for player rates
REGRESS = 0.75           # keep 75% of last season's team rating, relative to league average
CUR_HALF_GAMES = 15      # this season's team ratings get half the weight after this many games
IMPACT_SHRINK_MIN = 1500 # minutes of evidence that would justify half of an on/off split
# Calibrated on last season: teams' real with/without splits for 117 regular players moved
# about 2.7x the unscaled estimate; 1.4 stays a little conservative.
IMPACT_SCALE = 1.4
IMPACT_CAP = 10.0         # per 100 possessions, each of offence and defence
# Roster and minutes changes since last season are damped: a full-strength rotation is
# optimistic (players miss games) and part of each player's value is already in the team rating.
ROSTER_WEIGHT = 0.35
MARGIN_SD = 13.0         # spread of real NBA margins around a prediction
B2B_PENALTY = 1.5        # points of margin lost on the second night of a back-to-back
ROTATION_SIZE = 10
MAX_MINUTES = 40.0
GAME_TYPES = {"002": "Regular season", "004": "Playoffs", "005": "Play-in", "006": "NBA Cup final"}


def _poss(df: pd.DataFrame) -> pd.Series:
    return df["FGA"] - df["OREB"] + df["TOV"] + 0.44 * df["FTA"]


def win_probability(margin: float) -> float:
    return 0.5 * (1 + math.erf(margin / (MARGIN_SD * math.sqrt(2))))


@dataclass
class TeamSeason:
    gp: int = 0
    w: int = 0
    l: int = 0
    ortg: float = 0.0
    drtg: float = 0.0
    pace: float = 0.0
    last10: dict | None = None  # {"w", "l", "net", "season"}


@dataclass
class Player:
    id: int
    name: str
    team_id: int | None = None   # current roster team
    position: str = ""
    number: str = ""
    age: float | None = None
    how_acquired: str = ""
    mpg: float = 0.0             # expected minutes when available (before rotation scaling)
    rates: dict = field(default_factory=dict)   # per minute
    impact_off: float = 0.0      # per 100 possessions on court
    impact_def: float = 0.0      # positive = team allows fewer points with him on
    gp: dict = field(default_factory=dict)      # season -> games
    per_game: dict = field(default_factory=dict)  # season -> {stat: avg}

    @property
    def impact(self) -> float:
        return self.impact_off + self.impact_def


class League:
    def __init__(self):
        self.cur, self.prev = config.current_season(), config.previous_season()
        self.teams = {t["id"]: t for t in static_teams.get_teams()}
        for t in self.teams.values():
            t["conference"] = "East" if t["abbreviation"] in EAST else "West"
        self.by_abbr = {t["abbreviation"]: t["id"] for t in self.teams.values()}

        self.plogs = {s: self._load_logs(s, "P") for s in (self.cur, self.prev)}
        self.tlogs = {s: self._team_games(self._load_logs(s, "T")) for s in (self.cur, self.prev)}
        self.team_seasons = {s: self._team_seasons(s) for s in (self.cur, self.prev)}
        self.league = {s: self._league_avgs(s) for s in (self.cur, self.prev)}
        self.home_adv = self._home_advantage()
        self.shares = {s: self._minute_shares(s) for s in (self.cur, self.prev)}
        self.players: dict[int, Player] = {}
        self._build_players()
        self.schedule = self._schedule()
        # A full-strength rotation always looks better than last season's injury-hit minutes,
        # so lineup adjustments are measured against the league-average adjustment.
        self._full_cache: dict[int, dict] = {}
        parts = [self._full_strength(tid) for tid in self.teams]
        self._offset = {
            "adj_off": sum(p["adj_off"] for p in parts) / len(parts),
            "adj_def": sum(p["adj_def"] for p in parts) / len(parts),
        }

    # --- Loading ---------------------------------------------------------------

    @staticmethod
    def _load_logs(season, kind) -> pd.DataFrame:
        frames = nba.load(f"gamelog_{kind}_{season}")
        df = frames[0] if frames else pd.DataFrame()
        if len(df):
            df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"]).dt.date
        return df

    @staticmethod
    def _team_games(df: pd.DataFrame) -> pd.DataFrame:
        """One row per team per game, with the opponent's points and both teams' possessions."""
        if df.empty:
            return df
        df = df.copy()
        df["POSS"] = _poss(df)
        opp = df[["GAME_ID", "TEAM_ID", "PTS", "POSS"]].rename(
            columns={"TEAM_ID": "OPP_ID", "PTS": "OPP_PTS", "POSS": "OPP_POSS"}
        )
        df = df.merge(opp, on="GAME_ID")
        df = df[df["TEAM_ID"] != df["OPP_ID"]].copy()
        df["GAME_POSS"] = (df["POSS"] + df["OPP_POSS"]) / 2
        df["HOME"] = df["MATCHUP"].str.contains("vs.")
        return df.sort_values("GAME_DATE")

    def _team_seasons(self, season) -> dict[int, TeamSeason]:
        df = self.tlogs[season]
        out = {}
        if df.empty:
            return out
        for tid, g in df.groupby("TEAM_ID"):
            poss = g["GAME_POSS"].sum()
            last = g.tail(10)
            out[tid] = TeamSeason(
                gp=len(g),
                w=int((g["WL"] == "W").sum()),
                l=int((g["WL"] == "L").sum()),
                ortg=100 * g["PTS"].sum() / poss,
                drtg=100 * g["OPP_PTS"].sum() / poss,
                pace=48 * poss / (g["MIN"].sum() / 5),
                last10={
                    "w": int((last["WL"] == "W").sum()),
                    "l": int((last["WL"] == "L").sum()),
                    "net": 100 * (last["PTS"].sum() - last["OPP_PTS"].sum()) / last["GAME_POSS"].sum(),
                    "season": season,
                },
            )
        return out

    def _league_avgs(self, season) -> dict | None:
        df = self.tlogs[season]
        if df.empty:
            return None
        poss = df["GAME_POSS"].sum()
        return {"ortg": 100 * df["PTS"].sum() / poss, "pace": 48 * poss / (df["MIN"].sum() / 5), "games": len(df) // 2}

    def _home_advantage(self) -> float:
        frames = [d[d["HOME"]] for d in self.tlogs.values() if not d.empty]
        home = pd.concat(frames)
        return float((home["PTS"] - home["OPP_PTS"]).mean()) if len(home) else 2.5

    def _minute_shares(self, season) -> dict[tuple[int, int], float]:
        """(player, team) -> fraction of that team's minutes the player was on court for."""
        p, ts = self.plogs[season], self.team_seasons[season]
        if p.empty:
            return {}
        mins = p.groupby(["PLAYER_ID", "TEAM_ID"])["MIN"].sum()
        return {(pid, tid): m / (ts[tid].gp * 48) for (pid, tid), m in mins.items() if tid in ts}

    def _build_players(self):
        # Rosters decide who plays for whom now.
        for tid in self.teams:
            frames = nba.load(f"roster_{tid}_{self.cur}")
            if not frames:
                continue
            for r in frames[0].itertuples():
                self.players[r.PLAYER_ID] = Player(
                    id=r.PLAYER_ID, name=r.PLAYER, team_id=tid,
                    position=r.POSITION or "", number=str(r.NUM or "").removesuffix(".0") if r.NUM == r.NUM else "",
                    age=r.AGE, how_acquired=r.HOW_ACQUIRED or "",
                )

        # Season totals and per-game averages.
        totals = {}
        for season, weight in ((self.cur, 1.0), (self.prev, PREV_WEIGHT)):
            df = self.plogs[season]
            if df.empty:
                continue
            g = df.groupby("PLAYER_ID")
            sums = g[["MIN", *STATS]].sum()
            gp = g.size()
            names = g["PLAYER_NAME"].last()
            for pid, row in sums.iterrows():
                pl = self.players.get(pid) or self.players.setdefault(pid, Player(id=pid, name=names[pid]))
                pl.gp[season] = int(gp[pid])
                pl.per_game[season] = {k: row[k] / gp[pid] for k in ["MIN", *STATS]}
                t = totals.setdefault(pid, {"GP": 0.0, "MIN": 0.0, **{k: 0.0 for k in STATS}})
                t["GP"] += weight * gp[pid]
                for k in ["MIN", *STATS]:
                    t[k] += weight * row[k]

        # Prior for thin samples: per-minute rates of a typical bench player.
        all_t = pd.DataFrame(totals).T
        bench = all_t[(all_t["MIN"] / all_t["GP"]).between(8, 20)]
        prior = {k: bench[k].sum() / bench["MIN"].sum() for k in STATS} if len(bench) else {k: 0.0 for k in STATS}
        prior_min = 150

        for pl in self.players.values():
            t = totals.get(pl.id)
            if t and t["GP"] > 0:
                pl.mpg = (t["MIN"] + 3 * 10) / (t["GP"] + 3)
                pl.rates = {k: (t[k] + prior[k] * prior_min) / (t["MIN"] + prior_min) for k in STATS}
            else:
                pl.mpg = self._rookie_minutes(pl.how_acquired)
                pl.rates = dict(prior)

        self._build_impacts()

    def _rookie_minutes(self, how: str) -> float:
        m = re.search(r"#(\d+) Pick in (\d{4})", how)
        if m and int(m.group(2)) == int(self.cur[:4]):
            pick = int(m.group(1))
            return 24 if pick <= 5 else 18 if pick <= 14 else 12 if pick <= 30 else 8
        return 8

    def _build_impacts(self):
        acc: dict[int, list[float]] = {}  # pid -> [weight, off*weight, def*weight, on_min, off_min]
        for season, weight in ((self.cur, 1.0), (self.prev, PREV_WEIGHT)):
            for tid in self.teams:
                frames = nba.load(f"onoff_{tid}_{season}")
                if not frames or frames[0].empty:
                    continue
                df = frames[0]
                on = df[df["COURT_STATUS"] == "On"].set_index("VS_PLAYER_ID")
                off = df[df["COURT_STATUS"] == "Off"].set_index("VS_PLAYER_ID")
                for pid in on.index.intersection(off.index):
                    a, b = on.loc[pid], off.loc[pid]
                    if a["MIN"] <= 0 or b["MIN"] <= 0:
                        continue
                    w = weight * a["MIN"]
                    s = acc.setdefault(pid, [0.0, 0.0, 0.0, 0.0, 0.0])
                    s[0] += w
                    s[1] += w * (a["OFF_RATING"] - b["OFF_RATING"])
                    s[2] += w * (b["DEF_RATING"] - a["DEF_RATING"])
                    s[3] += weight * a["MIN"]
                    s[4] += weight * b["MIN"]
        for pid, (w, o, d, on_min, off_min) in acc.items():
            pl = self.players.get(pid)
            if pl is None:
                continue
            # Evidence is limited by whichever of on/off minutes is smaller.
            n = 1 / (1 / on_min + 1 / off_min)
            k = IMPACT_SCALE * n / (n + IMPACT_SHRINK_MIN / 4)
            pl.impact_off = max(-IMPACT_CAP, min(IMPACT_CAP, k * o / w))
            pl.impact_def = max(-IMPACT_CAP, min(IMPACT_CAP, k * d / w))

    def _schedule(self) -> pd.DataFrame:
        frames = nba.load(f"schedule_{self.cur}")
        if not frames:
            return pd.DataFrame()
        df = frames[0]
        df = df[df["gameId"].str[:3].isin(GAME_TYPES)].copy()
        df["start"] = pd.to_datetime(df["gameDateTimeUTC"], utc=True).dt.tz_convert(config.TZ)
        df["us_date"] = pd.to_datetime(df["gameDateEst"].str[:10]).dt.date
        return df.sort_values("start").reset_index(drop=True)

    # --- Team strength --------------------------------------------------------

    def roster(self, team_id: int) -> list[Player]:
        return [p for p in self.players.values() if p.team_id == team_id]

    def rotation(self, team_id: int, out: set[int]) -> dict[int, float]:
        """Expected minutes for each available player, adding up to 240.

        The top 10 by usual minutes play. When their usual minutes add up to more than 240,
        the end of the bench is squeezed and the main players keep their minutes; when they
        add up to less (players out), everyone's minutes are scaled up.
        """
        avail = sorted((p for p in self.roster(team_id) if p.id not in out), key=lambda p: -p.mpg)[:ROTATION_SIZE]
        total = sum(p.mpg for p in avail)
        if not total:
            return {}
        if total >= 240:
            mins, left = {}, 240.0
            for p in avail:
                mins[p.id] = min(p.mpg, left)
                left -= mins[p.id]
            return {pid: m for pid, m in mins.items() if m >= 1}
        mins = {p.id: p.mpg * 240 / total for p in avail}
        # Cap heavy minutes and hand the excess to the uncapped players.
        for _ in range(5):
            excess = sum(m - MAX_MINUTES for m in mins.values() if m > MAX_MINUTES)
            if excess <= 0:
                break
            free = {pid: m for pid, m in mins.items() if m < MAX_MINUTES}
            free_total = sum(free.values()) or 1
            mins = {pid: min(m, MAX_MINUTES) + (excess * m / free_total if pid in free else 0) for pid, m in mins.items()}
        return mins

    def _season_weight(self, team_id: int) -> float:
        gp = self.team_seasons[self.cur].get(team_id, TeamSeason()).gp
        return gp / (gp + CUR_HALF_GAMES)

    def league_avg(self) -> dict:
        prev, cur = self.league[self.prev], self.league[self.cur]
        if not cur:
            return prev
        w = cur["games"] / (cur["games"] + 15 * CUR_HALF_GAMES)
        return {k: w * cur[k] + (1 - w) * prev[k] for k in ("ortg", "pace")}

    def _impact_change(self, before: dict[int, float], after: dict[int, float]) -> tuple[float, float]:
        """Offence and defence change from moving players' shares of court time."""
        off = dfn = 0.0
        for pid in set(before) | set(after):
            pl = self.players.get(pid)
            if pl is None:
                continue
            delta = after.get(pid, 0.0) - before.get(pid, 0.0)
            off += pl.impact_off * delta
            dfn += pl.impact_def * delta
        return off, dfn

    def _full_strength(self, team_id: int) -> dict:
        """Ratings with everyone available: team form plus damped roster/minutes changes."""
        if team_id in self._full_cache:
            return self._full_cache[team_id]
        healthy = {pid: m / 48 for pid, m in self.rotation(team_id, set()).items()}
        w = self._season_weight(team_id)

        def from_season(season, regress):
            ts = self.team_seasons[season].get(team_id)
            lg = self.league[season]
            if not ts or not lg:
                return None
            then = {pid: s for (pid, tid), s in self.shares[season].items() if tid == team_id}
            adj_off, adj_def = self._impact_change(then, healthy)
            return {
                "off": regress * (ts.ortg - lg["ortg"]),
                "def": regress * (lg["ortg"] - ts.drtg),  # positive = better than average
                "pace": regress * (ts.pace - lg["pace"]),
                "adj_off": adj_off,
                "adj_def": adj_def,
            }

        prev = from_season(self.prev, REGRESS) or {"off": 0, "def": 0, "pace": 0, "adj_off": 0, "adj_def": 0}
        cur = from_season(self.cur, 1.0) if w > 0 else None
        parts = prev if cur is None else {k: w * cur[k] + (1 - w) * prev[k] for k in prev}
        parts["cur_weight"] = w
        self._full_cache[team_id] = parts
        return parts

    def strength(self, team_id: int, out: set[int]) -> dict:
        """Projected ratings relative to league average, with the parts that make them up."""
        parts = self._full_strength(team_id)
        mins = self.rotation(team_id, out)
        # Roster and minutes changes since the rated season count at ROSTER_WEIGHT, centred on
        # the league average; players marked out count in full.
        roster_off = ROSTER_WEIGHT * (parts["adj_off"] - self._offset["adj_off"])
        roster_def = ROSTER_WEIGHT * (parts["adj_def"] - self._offset["adj_def"])
        healthy = {pid: m / 48 for pid, m in self.rotation(team_id, set()).items()}
        out_off, out_def = self._impact_change(healthy, {pid: m / 48 for pid, m in mins.items()}) if out else (0.0, 0.0)
        return {
            "off": parts["off"] + roster_off + out_off,
            "def": parts["def"] + roster_def + out_def,
            "pace": parts["pace"],
            "base_net": parts["off"] + parts["def"],
            "roster_net": roster_off + roster_def,
            "out_net": out_off + out_def,
            "minutes": mins,
            "cur_weight": parts["cur_weight"],
        }

    # --- Predictions ------------------------------------------------------------

    def back_to_back(self, team_id: int, us_date: date) -> bool:
        df = self.schedule
        if df.empty:
            return False
        played = df[(df["homeTeam_teamId"] == team_id) | (df["awayTeam_teamId"] == team_id)]["us_date"]
        return (us_date - timedelta(days=1)) in set(played)

    def predict(self, home_id: int, away_id: int, out: set[int], us_date: date | None = None, neutral: bool = False) -> dict:
        lg = self.league_avg()
        h, a = self.strength(home_id, out), self.strength(away_id, out)
        pace = lg["pace"] + h["pace"] + a["pace"]
        hca = 0.0 if neutral else self.home_adv
        b2b = {
            "home": bool(us_date and self.back_to_back(home_id, us_date)),
            "away": bool(us_date and self.back_to_back(away_id, us_date)),
        }
        rest = B2B_PENALTY * (b2b["away"] - b2b["home"])
        home_pts = pace * (lg["ortg"] + h["off"] - a["def"]) / 100 + (hca + rest) / 2
        away_pts = pace * (lg["ortg"] + a["off"] - h["def"]) / 100 - (hca + rest) / 2
        margin = home_pts - away_pts
        return {
            "home": {"id": home_id, "pts": home_pts, "strength": h, "players": self._player_lines(home_id, h, home_pts, pace), "b2b": b2b["home"]},
            "away": {"id": away_id, "pts": away_pts, "strength": a, "players": self._player_lines(away_id, a, away_pts, pace), "b2b": b2b["away"]},
            "margin": margin,
            "home_win": win_probability(margin),
            "pace": pace,
            "factors": [
                ("Team ratings (season form)", pace * (h["base_net"] - a["base_net"]) / 100),
                ("Roster and minutes changes", pace * (h["roster_net"] - a["roster_net"]) / 100),
                ("Unavailable players", pace * (h["out_net"] - a["out_net"]) / 100),
                ("Home court" if hca else "Neutral site", hca),
                ("Back-to-back", rest),
            ],
        }

    def _player_lines(self, team_id: int, s: dict, team_pts: float, pace: float) -> list[dict]:
        mins = s["minutes"]
        raw = {pid: {k: self.players[pid].rates.get(k, 0) * m for k in STATS} for pid, m in mins.items()}
        raw_pts = sum(r["PTS"] for r in raw.values()) or 1
        score_scale = team_pts / raw_pts
        ts = self.team_seasons[self.cur].get(team_id) or self.team_seasons[self.prev].get(team_id)
        pace_scale = pace / ts.pace if ts and ts.pace else 1.0
        lines = []
        for pid, m in sorted(mins.items(), key=lambda kv: -kv[1]):
            r = raw[pid]
            line = {k: r[k] * (score_scale if k in SCORING_STATS else pace_scale) for k in STATS}
            lines.append({"player": self.players[pid], "MIN": m, **line})
        return lines

    # --- Evidence ----------------------------------------------------------------

    def games_without(self, player_id: int, team_id: int) -> list[dict]:
        """Per season: the team's record with and without the player while he was on the team."""
        out = []
        for season in (self.cur, self.prev):
            p, t = self.plogs[season], self.tlogs[season]
            if p.empty:
                continue
            mine = p[(p["PLAYER_ID"] == player_id) & (p["TEAM_ID"] == team_id)]
            if mine.empty:
                continue
            first, last = mine["GAME_DATE"].min(), mine["GAME_DATE"].max()
            if season == self.cur and self.players.get(player_id) and self.players[player_id].team_id == team_id:
                last = date.max  # still on the team
            games = t[(t["TEAM_ID"] == team_id) & (t["GAME_DATE"] >= first) & (t["GAME_DATE"] <= last)]
            played = games["GAME_ID"].isin(set(mine["GAME_ID"]))

            def summary(g):
                if g.empty:
                    return None
                return {"gp": len(g), "w": int((g["WL"] == "W").sum()), "l": int((g["WL"] == "L").sum()),
                        "net": 100 * (g["PTS"].sum() - g["OPP_PTS"].sum()) / g["GAME_POSS"].sum()}

            out.append({"season": season, "with": summary(games[played]), "without": summary(games[~played])})
        return out

    def head_to_head(self, team_a: int, team_b: int) -> list[dict]:
        rows = []
        for season in (self.cur, self.prev):
            t = self.tlogs[season]
            if t.empty:
                continue
            g = t[(t["TEAM_ID"] == team_a) & (t["OPP_ID"] == team_b)]
            rows += [{"date": r.GAME_DATE, "home": r.HOME, "pts": r.PTS, "opp": r.OPP_PTS, "wl": r.WL, "game_id": r.GAME_ID} for r in g.itertuples()]
        return sorted(rows, key=lambda r: r["date"], reverse=True)

    def box_score(self, game_id: str) -> dict[int, list[dict]]:
        """Actual player lines for a finished game, by team."""
        df = self.plogs[self.cur]
        if df.empty:
            return {}
        g = df[df["GAME_ID"] == game_id].sort_values("MIN", ascending=False)
        return {tid: grp.to_dict("records") for tid, grp in g.groupby("TEAM_ID")}


_cache: dict = {"sig": None, "league": None}


def league() -> League:
    """The League built from the current cache, rebuilt whenever a cached file changes."""
    files = list(config.CACHE_DIR.glob("*.json")) if config.CACHE_DIR.exists() else []
    sig = (len(files), max((f.stat().st_mtime for f in files), default=0))
    if _cache["sig"] != sig:
        _cache["league"] = League()
        _cache["sig"] = sig
    return _cache["league"]
