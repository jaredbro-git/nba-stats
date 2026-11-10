"""The phone bundle: everything the Android app needs to make predictions, in one SQLite file.

The Mac does the heavy work (downloads, team ratings, player impact, matchup and defender ratings,
playstyle); the bundle holds the results, and the phone's Kotlin port of the prediction maths
(rotation, strength, predict, matchups) works from them. Live things (scores, box scores, shot charts,
career stats) the phone fetches from stats.nba.com itself.

Tables (see build()): meta, teams, team_strength, team_seasons, players, games, player_games,
team_games, pairs, player_names, predictions. `python -m app.bundle out.db [expected.json]` builds one; the
expected file holds Python's answers for a set of predictions and matchups, which the phone's tests
must reproduce.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

from . import availability, config, injuries, matchups, model, profile, tracker

# Bump whenever the tables change, so the Mac rebuilds the bundle and the phone can tell an old one.
FORMAT = 3

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE teams (id INTEGER PRIMARY KEY, abbr TEXT, name TEXT, nickname TEXT, city TEXT, conference TEXT);
CREATE TABLE team_strength (team_id INTEGER PRIMARY KEY, off REAL, def REAL, pace REAL, adj_off REAL, adj_def REAL, cur_weight REAL);
CREATE TABLE team_seasons (team_id INTEGER, season TEXT, gp INTEGER, w INTEGER, l INTEGER, ortg REAL, drtg REAL, pace REAL,
    l10_w INTEGER, l10_l INTEGER, l10_net REAL, PRIMARY KEY (team_id, season));
CREATE TABLE players (id INTEGER PRIMARY KEY, ord INTEGER, name TEXT, team_id INTEGER, position TEXT, number TEXT, age REAL, height REAL,
    how_acquired TEXT, mpg REAL, impact_off REAL, impact_def REAL, rates TEXT, per_game TEXT, gp TEXT,
    def_rating REAL, def_fg REAL, def_fg3 REAL, shooter_rate REAL, base_fg REAL, base_fg3 REAL, per_poss TEXT,
    style_season TEXT, summary TEXT, traits TEXT, similar TEXT, ts REAL, usg REAL, ast_pct REAL);
CREATE TABLE games (game_id TEXT PRIMARY KEY, start_utc TEXT, us_date TEXT, home_id INTEGER, away_id INTEGER, status INTEGER,
    status_text TEXT, home_score INTEGER, away_score INTEGER, neutral INTEGER, label TEXT, sublabel TEXT, arena TEXT, city TEXT);
CREATE TABLE player_games (season TEXT, game_id TEXT, date TEXT, player_id INTEGER, player_name TEXT, team_id INTEGER, matchup TEXT,
    wl TEXT, min REAL, pts INTEGER, reb INTEGER, ast INTEGER, fg3m INTEGER, fg3a INTEGER, fgm INTEGER, fga INTEGER,
    stl INTEGER, blk INTEGER, tov INTEGER, plus_minus REAL);
CREATE INDEX player_games_game ON player_games (game_id);
CREATE INDEX player_games_player ON player_games (player_id);
CREATE TABLE team_games (season TEXT, game_id TEXT, date TEXT, team_id INTEGER, opp_id INTEGER, home INTEGER, pts INTEGER,
    opp_pts INTEGER, poss REAL, wl TEXT, min REAL);
CREATE INDEX team_games_team ON team_games (team_id);
CREATE TABLE pairs (off_id INTEGER, def_id INTEGER, poss_w REAL, effect REAL, fgm_w REAL, fga_w REAL, diff REAL,
    poss REAL, pts INTEGER, fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ast INTEGER, tov INTEGER, fta INTEGER, gp INTEGER,
    PRIMARY KEY (off_id, def_id)) WITHOUT ROWID;
CREATE INDEX pairs_def ON pairs (def_id);
CREATE TABLE player_names (id INTEGER PRIMARY KEY, name TEXT);
-- The Mac's prediction tracker (tracker.py): each game's prediction saved before tip-off, and the result once final.
CREATE TABLE predictions (game_id TEXT PRIMARY KEY, kind TEXT, start_utc TEXT, home_id INTEGER, away_id INTEGER,
  home_pts REAL, away_pts REAL, home_win REAL, logged_at TEXT, backfilled INTEGER, home_score INTEGER, away_score INTEGER,
  source TEXT);   -- "iphone" for a pick the phone saved (tracker.merge_phone), else the Mac's
"""


def _num(v):
    """JSON/SQLite-friendly number (numpy types and NaN become plain values / NULL)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return None if f != f else f


def _injuries() -> dict:
    data = injuries.load()
    per_game, carried = injuries.outs(data)
    return {
        "published": data.get("published"),
        "games": {gid: sorted(ids) for gid, ids in per_game.items()},
        "carried": sorted(carried),
        "notes": {str(pid): {"status": e["status"], "reason": e["reason"]} for pid, e in injuries.player_notes(data).items()},
        # The full state, so the phone can merge reports it reads itself on top (ios Injuries.swift).
        "state": {k: data.get(k, {}) for k in ("games", "players")},
    }


def build(out: Path) -> dict:
    """Write the bundle to `out` (replacing it). Returns its meta."""
    started = time.time()
    lg = model.league()
    m = matchups.load(lg)
    out.unlink(missing_ok=True)
    db = sqlite3.connect(out)
    db.executescript(SCHEMA)

    league = lg.league_avg()
    meta = {
        "version": int(time.time()), "format": FORMAT, "cur": lg.cur, "prev": lg.prev,
        "league_ortg": _num(league["ortg"]), "league_pace": _num(league["pace"]), "home_adv": _num(lg.home_adv),
        "offset_off": _num(lg._offset["adj_off"]), "offset_def": _num(lg._offset["adj_def"]),
        "roster_weight": 1.0,   # team_strength adj_off/adj_def come already weighted (model._full_strength)
        "absence_weight": model.ABSENCE_WEIGHT, "margin_sd": model.MARGIN_SD, "b2b_penalty": model.B2B_PENALTY,
        "rotation_size": model.ROTATION_SIZE, "max_minutes": model.MAX_MINUTES,
        "primary_share": matchups.PRIMARY_SHARE, "pass_through": matchups.PASS_THROUGH, "pair_shrink": matchups.PAIR_SHRINK,
        "fg_shrink": matchups.FG_SHRINK, "three_shrink": matchups.THREE_SHRINK, "shooters_per_team": matchups.SHOOTERS_PER_TEAM,
        "size_pts": _num(m.size_pts), "size_fg": _num(m.size_fg), "league_fg": _num(m.league_fg), "league_fg3": _num(m.league_fg3),
        "first_matchup_season": m.first_season,
        "how_tracked": tracker.HOW_TRACKED,
        "game_outs": {gid: sorted(ids) for gid, ids in availability.game_outs().items()},
        "unavailable": sorted(json.loads(config.UNAVAILABLE_FILE.read_text())) if config.UNAVAILABLE_FILE.exists() else [],
        # The NBA injury report (injuries.py): per-game outs for games in a report, players carried forward as
        # out for later games, and each listed player's status for display.
        "injuries": _injuries(),
        # So the phone can redo team ratings and minutes itself when it has results newer than this bundle
        # (ios Ratings.swift, a port of model.League's team and player parts).
        "rating_params": {"prev_weight": model.PREV_WEIGHT, "regress": model.REGRESS, "cur_half_games": model.CUR_HALF_GAMES,
                          "roster_weight": model.ROSTER_WEIGHT, "cur_roster_weight": model.CUR_ROSTER_WEIGHT},
    }

    db.executemany("INSERT INTO teams VALUES (?,?,?,?,?,?)",
                   [(t["id"], t["abbreviation"], t["full_name"], t["nickname"], t["city"], t["conference"]) for t in lg.teams.values()])
    db.executemany("INSERT INTO team_strength VALUES (?,?,?,?,?,?,?)",
                   [(tid, *(_num(p[k]) for k in ("off", "def", "pace", "adj_off", "adj_def", "cur_weight")))
                    for tid, p in ((tid, lg._full_strength(tid)) for tid in lg.teams)])
    db.executemany("INSERT INTO team_seasons VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (tid, season, ts.gp, ts.w, ts.l, _num(ts.ortg), _num(ts.drtg), _num(ts.pace),
         (ts.last10 or {}).get("w"), (ts.last10 or {}).get("l"), _num((ts.last10 or {}).get("net")))
        for season in (lg.cur, lg.prev) for tid, ts in lg.team_seasons[season].items()])

    # Players: everyone in the model (rosters plus anyone with recent games).
    style = {}
    for season in (lg.cur, lg.prev):
        table = profile.season_table(lg, season)
        if not table.empty:
            style[season] = (table, table[table["MIN"] >= profile.QUALIFY_MIN])
    rows = []
    # `ord` keeps the model's player order, which breaks ties when sorting rotations (as in Python).
    for ord_, pl in enumerate(lg.players.values()):
        traits, summary, style_season, adv = [], None, None, {}
        season = profile._season_for(lg, pl.id)
        if season in style and pl.id in style[season][0].index:
            table, q = style[season]
            row = table.loc[pl.id]
            traits = profile._traits(row, q)
            summary = profile._summary(pl.name, pl.position, traits, row["MIN"] / row["GP"])
            style_season, adv = season, row.to_dict()
        similar = []
        if pl.team_id:
            _, sims = profile.similar(lg, pl.id)
            similar = [{"id": s["id"], "match": round(s["match"], 4)} for s in sims]
        rows.append((
            pl.id, ord_, pl.name, pl.team_id, pl.position, pl.number, _num(pl.age), _num(pl.height), pl.how_acquired, _num(pl.mpg),
            _num(pl.impact_off), _num(pl.impact_def), json.dumps({k: _num(v) for k, v in pl.rates.items()}),
            json.dumps({s: {k: _num(v) for k, v in pg.items()} for s, pg in pl.per_game.items()}), json.dumps(pl.gp),
            _num(m.defender.get(pl.id)), _num(m.defender_fg.get(pl.id)), _num(m.defender_fg3.get(pl.id)),
            _num(m.rate.get(pl.id)), _num(m.base_fg.get(pl.id)), _num(m.base_fg3.get(pl.id)),
            json.dumps({k: _num(v.get(pl.id)) for k, v in m.per_poss.items()}),
            style_season, summary, json.dumps(traits), json.dumps(similar),
            _num(adv.get("TS_PCT")), _num(adv.get("USG_PCT")), _num(adv.get("AST_PCT")),
        ))
    db.executemany(f"INSERT INTO players VALUES ({','.join('?' * 29)})", rows)

    g = lg.all_games
    db.executemany("INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (r.gameId, r.start.tz_convert("UTC").isoformat(), r.us_date.isoformat(), int(r.homeTeam_teamId), int(r.awayTeam_teamId),
         int(r.gameStatus), r.gameStatusText, int(r.homeTeam_score or 0), int(r.awayTeam_score or 0), int(bool(r.isNeutral)),
         r.gameLabel or "", r.gameSubLabel or "", r.arenaName or "", r.arenaCity or "")
        for r in g.itertuples()])

    for season in (lg.cur, lg.prev):
        p = lg.plogs[season]
        if not p.empty:
            db.executemany(f"INSERT INTO player_games VALUES ({','.join('?' * 20)})", [
                (season, r.GAME_ID, r.GAME_DATE.isoformat(), r.PLAYER_ID, r.PLAYER_NAME, r.TEAM_ID, r.MATCHUP, r.WL, _num(r.MIN),
                 r.PTS, r.REB, r.AST, r.FG3M, r.FG3A, r.FGM, r.FGA, r.STL, r.BLK, r.TOV, _num(r.PLUS_MINUS))
                for r in p.itertuples()])
        t = lg.tlogs[season]
        if not t.empty:
            db.executemany("INSERT INTO team_games VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
                (season, r.GAME_ID, r.GAME_DATE.isoformat(), r.TEAM_ID, r.OPP_ID, int(r.HOME), r.PTS, r.OPP_PTS, _num(r.GAME_POSS), r.WL,
                 _num(r.MIN))
                for r in t.itertuples()])

    # Matchup pairs where either player is on a roster now (retired-vs-retired pairs aren't needed).
    rostered = {p.id for p in lg.players.values() if p.team_id}
    raw = m._rows.groupby(level=[0, 1])[matchups.COLS].sum()
    pw = m._pair_w.join(raw, how="inner")
    keep = pw.index.get_level_values(0).isin(rostered) | pw.index.get_level_values(1).isin(rostered)
    pw = pw[keep]
    db.executemany(f"INSERT INTO pairs VALUES ({','.join('?' * 17)})", [
        (int(o), int(d), _num(r.POSS_W), _num(r.EFFECT), _num(r.FGM_W), _num(r.FGA_W), _num(r.DIFF), _num(r.PARTIAL_POSS),
         int(r.PLAYER_PTS), int(r.MATCHUP_FGM), int(r.MATCHUP_FGA), int(r.MATCHUP_FG3M), int(r.MATCHUP_FG3A),
         int(r.MATCHUP_AST), int(r.MATCHUP_TOV), int(r.MATCHUP_FTA), int(r.GP))
        for (o, d), r in zip(pw.index, pw.itertuples(index=False))])

    from .main import _player_names
    db.executemany("INSERT INTO player_names VALUES (?,?)", [(pid, name) for pid, (name, _) in _player_names().items()])
    db.executemany("INSERT INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (r["game_id"], r["kind"], r["start"], r["home"], r["away"], r["home_pts"], r["away_pts"], r["home_win"],
         r["logged_at"], int(bool(r.get("backfilled"))), (r.get("result") or {}).get("home"), (r.get("result") or {}).get("away"),
         r.get("source", "mac"))
        for r in tracker.load().values()])

    meta["build_seconds"] = round(time.time() - started, 1)
    db.executemany("INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
    db.commit()
    db.execute("VACUUM")
    db.close()
    return meta


def expected(lg=None) -> dict:
    """Python's answers for a spread of predictions and matchups; the phone's tests compare against these."""
    lg = lg or model.league()
    m = matchups.load(lg)
    games = lg.schedule[(lg.schedule["gameId"].str[:3] == "002")].head(12)
    name = {p.name: p.id for p in lg.players.values()}
    cases = []
    for i, g in enumerate(games.itertuples()):
        home, away = int(g.homeTeam_teamId), int(g.awayTeam_teamId)
        if home not in lg.teams or away not in lg.teams:
            continue
        # Every other game, mark each team's top scorer out, to exercise the absence maths.
        out = set()
        if i % 2:
            for t in (home, away):
                best = max(lg.roster(t), key=lambda p: p.mpg, default=None)
                if best:
                    out.add(best.id)
        p = lg.predict(home, away, out, g.us_date, bool(g.isNeutral), with_matchups=True)
        cases.append({
            "game_id": g.gameId, "home": home, "away": away, "out": sorted(out), "us_date": g.us_date.isoformat(),
            "neutral": bool(g.isNeutral), "home_pts": p["home"]["pts"], "away_pts": p["away"]["pts"], "home_win": p["home_win"],
            "home_lines": [{"id": l["player"].id, "MIN": l["MIN"], "PTS": l["PTS"], "REB": l["REB"], "AST": l["AST"]} for l in p["home"]["players"]],
            "likely": {str(r["shooter"].id): r["likely"] for side in p["matchups"].values() for r in side["rows"]},
        })
    # A matchup change on one game.
    okc, mn = lg.by_abbr["OKC"], lg.by_abbr["MIN"]
    sga, gobert = name.get("Shai Gilgeous-Alexander"), name.get("Rudy Gobert")
    change = lg.predict(okc, mn, set(), None, False, matchups={sga: gobert})
    estimates = []
    for s_name, d_name in [("Shai Gilgeous-Alexander", "Jaden McDaniels"), ("Shai Gilgeous-Alexander", "Rudy Gobert"),
                           ("LeBron James", "Kevin Durant"), ("Nikola Jokić", "Rudy Gobert")]:
        if s_name in name and d_name in name:
            e = m.estimate(name[s_name], name[d_name])
            estimates.append({"shooter": name[s_name], "defender": name[d_name],
                              **{k: e[k] for k in ("pts100", "fg", "fg3", "effect100")}})
    # The season simulator: one run healthy, one with the best player in the league out for the season.
    from . import simulator
    star = max(lg.players.values(), key=lambda p: p.impact * (p.team_id is not None))
    sims = []
    for missing in ({}, {star.id: None}):
        r = simulator.run(lg, missing)
        sims.append({"missing": {str(k): v for k, v in missing.items()}, "team_sd": r["team_sd"], "games_left": r["games_left"],
                     "teams": {str(t["team"]["id"]): {k: t[k] for k in ("wins", "losses", "playoffs", "title", "seed1")}
                               for t in r["teams"]}})
    return {"sims": sims, "cases": cases, "matchup_change": {"home": okc, "away": mn, "shooter": sga, "defender": gobert,
                                               "home_pts": change["home"]["pts"], "away_pts": change["away"]["pts"]},
            "estimates": estimates}


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "bundle.db")
    info = build(target)
    print(f"Built {target} ({target.stat().st_size / 1e6:.1f} MB) in {info['build_seconds']} s")
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps(expected(), indent=1, default=float))
        print(f"Wrote {sys.argv[2]}")
