"""Season simulator: plays out the rest of the regular season, the play-in and the playoffs many times.

Each remaining game's home win chance comes from the game model (model.quick_margin), with players
marked unavailable for the games they'll miss. On top of the usual game-to-game randomness, every
simulated season draws each team's true strength from a spread around its projection (team_sd: wider
before the season, narrower as games are played): nobody
knows exactly how good a team is, and without this the odds come out far too certain.

Format: top six in each conference make the playoffs; 7-10 play in (7 v 8 for the 7 seed; the loser
plays the winner of 9 v 10 for the 8 seed). Best-of-seven series, higher seed hosting games 1, 2, 5
and 7; the Finals are hosted by the team with more wins. Ties in the standings are broken at random.
"""

import math
import numpy as np

from . import model

SIMS = 10_000
GAMES_PER_TEAM = 82
# Uncertainty in each team's true strength (points of margin) for the rest of the season. Preseason team
# projections typically miss by 3.5-4 points of net rating; as games are played the ratings firm up.
TEAM_SD_START, TEAM_SD_FLOOR = 3.5, 1.5
HOME_GAMES = [True, True, False, False, True, False, True]  # from the higher seed's side


def _norm_cdf(x: np.ndarray) -> np.ndarray:
    # erf for arrays without scipy: Abramowitz-Stegun 7.1.26 (error < 1.5e-7).
    sign = np.sign(x)
    z = np.abs(x) / math.sqrt(2)
    t = 1 / (1 + 0.3275911 * z)
    y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-z * z)
    return 0.5 * (1 + sign * y)


def series_win(p_home: np.ndarray, p_away: np.ndarray) -> np.ndarray:
    """Chance the higher seed wins a best-of-seven, given its win chance at home and away (game by game)."""
    states = {(0, 0): np.ones_like(p_home)}   # (higher seed's wins, losses) -> probability
    won = np.zeros_like(p_home)
    for game in range(7):
        p = p_home if HOME_GAMES[game] else p_away
        nxt: dict = {}
        for (w, l), prob in states.items():
            for nw, nl, q in ((w + 1, l, p), (w, l + 1, 1 - p)):
                if nw == 4:
                    won = won + prob * q
                elif nl < 4:
                    nxt[(nw, nl)] = nxt.get((nw, nl), 0) + prob * q
        states = nxt
    return won


def run(lg: model.League, missing: dict[int, int | None], seed: int = 7) -> dict:
    """missing: player id -> games he misses from now (None = rest of season, playoffs included)."""
    rng = np.random.default_rng(seed)
    teams = sorted(lg.teams)
    index = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    base_w = np.array([(lg.team_seasons[lg.cur].get(t) or model.TeamSeason()).w for t in teams], float)
    base_l = np.array([(lg.team_seasons[lg.cur].get(t) or model.TeamSeason()).l for t in teams], float)

    games = lg.schedule[(lg.schedule["gameId"].str[:3] == "002") & (lg.schedule["gameStatus"] != 3)]
    played_so_far = {t: 0 for t in teams}
    H, A, M = [], [], []
    for g in games.itertuples():
        h, a = g.homeTeam_teamId, g.awayTeam_teamId
        if h not in index or a not in index:
            continue  # e.g. NBA Cup knockout games, whose teams aren't decided yet
        out = set()
        for pid, count in missing.items():
            pl = lg.players.get(pid)
            if pl and pl.team_id in (h, a) and (count is None or played_so_far[pl.team_id] < count):
                out.add(pid)
        M.append(lg.quick_margin(h, a, out, g.us_date, bool(g.isNeutral)))
        H.append(index[h])
        A.append(index[a])
        played_so_far[h] += 1
        played_so_far[a] += 1
    # Games not on the schedule yet (NBA Cup knockouts and the extra games for teams knocked out of the
    # Cup are scheduled later) are played against a league-average opponent at a neutral site, so every
    # team plays 82. The average opponent is index n, with no strength of its own.
    scheduled = base_w + base_l + np.bincount(H, minlength=n) + np.bincount(A, minlength=n)
    pace = lg.league_avg()["pace"]
    for t in teams:
        i = index[t]
        for _ in range(max(0, GAMES_PER_TEAM - int(scheduled[i]))):
            out = {pid for pid, count in missing.items() if lg.players.get(pid) and lg.players[pid].team_id == t}
            H.append(i)
            A.append(n)
            M.append(pace * lg.net_rating(t, out) / 100)
    H, A, M = np.array(H, int), np.array(A, int), np.array(M, float)

    # How settled the ratings are: the share of weight this season's games get in the team ratings (0 before
    # the season, about 0.75 by mid-season), averaged across teams.
    settled = float(np.mean([lg._season_weight(t) for t in teams]))
    team_sd = TEAM_SD_FLOOR + (TEAM_SD_START - TEAM_SD_FLOOR) * (1 - settled)
    strength = rng.normal(0, team_sd, (SIMS, n + 1))  # each season's "true" team strength, in points
    strength[:, n] = 0.0  # the league-average opponent
    wins = np.tile(base_w, (SIMS, 1))
    for start in range(0, SIMS, 2000):  # in chunks to keep memory small
        s = slice(start, start + 2000)
        margin = M[None, :] + strength[s][:, H] - strength[s][:, A]
        home_won = rng.random(margin.shape) < _norm_cdf(margin / model.MARGIN_SD)
        for t in range(n):
            wins[s, t] += home_won[:, H == t].sum(1) + (~home_won[:, A == t]).sum(1)
    total_games = base_w + base_l + np.bincount(H, minlength=n + 1)[:n] + np.bincount(A, minlength=n + 1)[:n]

    # Playoff strength: healthy apart from players out for the rest of the season.
    season_out = {pid for pid, count in missing.items() if count is None}
    net = np.array([lg.net_rating(t, season_out) for t in teams])

    def p_win(home: np.ndarray, away: np.ndarray, rows: np.ndarray, hca: float) -> np.ndarray:
        m = pace * (net[home] - net[away]) / 100 + hca + strength[rows, home] - strength[rows, away]
        return _norm_cdf(m / model.MARGIN_SD)

    rows = np.arange(SIMS)
    hca = lg.home_adv
    seeds_out = {}
    reach = {k: np.zeros((SIMS, n), bool) for k in ("top6", "playin", "playoffs", "round2", "conf_finals", "finals", "title")}
    seed1 = np.zeros((SIMS, n), bool)
    champions = []
    for conf in ("East", "West"):
        members = np.array([index[t] for t in teams if lg.teams[t]["conference"] == conf])
        # Standings with random tie-breaks.
        order = np.argsort(-(wins[:, members] + rng.random((SIMS, len(members))) * 1e-3), axis=1)
        ranked = members[order]  # (SIMS, 15) team indices, best first
        seeds_out[conf] = ranked
        seed1[rows, ranked[:, 0]] = True
        for k in range(6):
            reach["top6"][rows, ranked[:, k]] = True
        for k in range(6, 10):
            reach["playin"][rows, ranked[:, k]] = True
        # Play-in: 7 v 8 (winner is the 7 seed), 9 v 10, then loser of 7/8 v winner of 9/10 for the 8 seed.
        s7, s8, s9, s10 = ranked[:, 6], ranked[:, 7], ranked[:, 8], ranked[:, 9]
        w78 = rng.random(SIMS) < p_win(s7, s8, rows, hca)
        seven = np.where(w78, s7, s8)
        loser78 = np.where(w78, s8, s7)
        w910 = rng.random(SIMS) < p_win(s9, s10, rows, hca)
        nine = np.where(w910, s9, s10)
        w_last = rng.random(SIMS) < p_win(loser78, nine, rows, hca)
        eight = np.where(w_last, loser78, nine)
        bracket = [ranked[:, 0], eight, ranked[:, 3], ranked[:, 4], ranked[:, 2], ranked[:, 5], ranked[:, 1], seven]
        for team in bracket:
            reach["playoffs"][rows, team] = True

        def series(hi: np.ndarray, lo: np.ndarray) -> np.ndarray:
            ph = p_win(hi, lo, rows, hca)
            pa = 1 - p_win(lo, hi, rows, hca)
            return np.where(rng.random(SIMS) < series_win(ph, pa), hi, lo)

        # Round 1 (1v8, 4v5, 3v6, 2v7), then the bracket halves meet; the better seed hosts.
        r1 = [series(bracket[i], bracket[i + 1]) for i in range(0, 8, 2)]
        for team in r1:
            reach["round2"][rows, team] = True
        seed_of = np.zeros((SIMS, n), int)
        seed_of[rows[:, None], ranked] = np.arange(1, 16)

        def by_seed(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            a_first = seed_of[rows, a] < seed_of[rows, b]
            return np.where(a_first, a, b), np.where(a_first, b, a)

        r2 = [series(*by_seed(r1[0], r1[1])), series(*by_seed(r1[2], r1[3]))]
        for team in r2:
            reach["conf_finals"][rows, team] = True
        champ = series(*by_seed(r2[0], r2[1]))
        reach["finals"][rows, champ] = True
        champions.append(champ)

    east, west = champions
    east_first = wins[rows, east] + rng.random(SIMS) * 1e-3 > wins[rows, west]
    hi, lo = np.where(east_first, east, west), np.where(east_first, west, east)
    ph, pa = p_win(hi, lo, rows, hca), 1 - p_win(lo, hi, rows, hca)
    title = np.where(rng.random(SIMS) < series_win(ph, pa), hi, lo)
    reach["title"][rows, title] = True

    results = []
    for t in teams:
        i = index[t]
        w = wins[:, i]
        results.append({
            "team": lg.teams[t], "conference": lg.teams[t]["conference"],
            "wins": float(w.mean()), "losses": float(total_games[i] - w.mean()),
            "low": int(np.percentile(w, 10)), "high": int(np.percentile(w, 90)),
            "record": (int(base_w[i]), int(base_l[i])), "seed1": float(seed1[:, i].mean()),
            **{k: float(v[:, i].mean()) for k, v in reach.items()},
        })
    return {"teams": results, "sims": SIMS, "games_left": len(games), "team_sd": team_sd}
