import json
import os
import threading
import time
import traceback
import unicodedata
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import availability, config, injuries, matchups, model, nba, phone, profile, shots, simulator, sync, tracker


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The Wi-Fi link to the Android app (set NBA_STATS_NO_PHONE=1 for test servers).
    if not os.getenv("NBA_STATS_NO_PHONE"):
        phone.start()
    if not os.getenv("NBA_STATS_NO_BACKGROUND"):
        threading.Thread(target=_background, daemon=True, name="background").start()
    yield


app = FastAPI(title="NBA", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=config.BASE_DIR / "app" / "templates")
templates.env.globals["asset_version"] = str(int(time.time()))
templates.env.globals["court_svg"] = shots.court_svg
# Pages in the top navigation, in order.
# (href, label, other paths that belong to the page, e.g. a team's games belong to Teams)
templates.env.globals["nav"] = [
    ("/", "Teams", ("/team/", "/game/", "/matchup")),
    ("/today", "Today", ()),
    ("/players", "Players", ()),
    ("/predictions", "Predictions", ()),
    ("/simulator", "Season sim", ()),
    ("/trades", "Trade machine", ()),
    ("/phone", "Phone", ()),
]
templates.env.globals["logo"] = lambda team_id: f"https://cdn.nba.com/logos/nba/{team_id}/global/L/logo.svg"
templates.env.globals["headshot"] = lambda pid: f"https://cdn.nba.com/headshots/nba/latest/260x190/{pid}.png"
templates.env.globals["height"] = lambda h: (
    f"{h.split('-')[0]}′{h.split('-')[1]}″ ({round(2.54 * (12 * int(h.split('-')[0]) + int(h.split('-')[1])))} cm)" if h and "-" in h else h
)
def _signed(v: float, d: int = 1) -> str:
    """+1.5 / −1.5 / 0.0, with the sign decided after rounding (so -0.4 to 0 places is "0", not "−0")."""
    text = f"{abs(v):.{d}f}"
    if float(text) == 0:
        return text
    return f"{'+' if v > 0 else '−'}{text}"


templates.env.filters["signed"] = _signed
templates.env.filters["pct"] = lambda v, d=0: "–" if v is None else f"{100 * v:.{d}f}%"


# --- Who's out (see availability.py) ------------------------------------------

saved_out = availability.saved_out
_save_out = availability.save_out


def _out_for(lg: model.League):
    """out_for(game_id, home, away) for many games, reading the saved lists and injury report once."""
    outs, saved, auto = availability.game_outs(), saved_out(), injuries.outs()
    return lambda game_id, home, away: availability.out_for_game(lg, game_id, home, away, outs, saved, auto)


def _sim_inputs(games: int | None) -> tuple[dict, dict]:
    """The simulator's (missing, game_outs): players on the all-games list or listed Out on the injury report
    miss their next `games` games; games with their own list, or in an injury report, use that list."""
    saved, auto = saved_out(), injuries.outs()
    missing = {pid: games for pid in availability.now_out(saved, auto)}
    per_game = {gid: saved | ids for gid, ids in auto[0].items()}
    return missing, {**per_game, **availability.game_outs()}


def _check_injuries(lg: model.League, force: bool = False) -> None:
    """Read any new injury report; if it changed anything, re-save the coming week's predictions straight away."""
    if injuries.check(lg, force):
        tracker.update(lg, _out_for(lg), force=True)


def _parse_matchups(text: str | None) -> dict[int, int]:
    pairs = {}
    for part in (text or "").split(","):
        shooter, _, defender = part.partition(":")
        if shooter.strip().isdigit() and defender.strip().isdigit():
            pairs[int(shooter)] = int(defender)
    return pairs


def _parse_ids(text: str | None) -> set[int]:
    return {int(x) for x in (text or "").split(",") if x.strip().isdigit()}


# --- Pages ---------------------------------------------------------------------

_tracked_generation = -1


def _track(lg: model.League) -> None:
    """Save predictions for the coming week's games, straight after each data refresh."""
    global _tracked_generation
    generation = sync.status()["generation"]
    tracker.update(lg, _out_for(lg), force=generation != _tracked_generation)
    _tracked_generation = generation


BACKGROUND_MINUTES = 10


def _background() -> None:
    """While the app is open (even untouched): refresh data when it's stale or a game's results are due,
    and keep the saved predictions up to date, so the tracker doesn't depend on pages being opened."""
    while True:
        try:
            sync.start()
            if sync.has_core_data() and not sync.status()["running"]:
                lg = model.league()
                _check_injuries(lg)
                _track(lg)
        except Exception:
            traceback.print_exc()
        # Check back soon while a refresh is running, so the predictions catch up as soon as it's done.
        time.sleep(60 if sync.status()["running"] else BACKGROUND_MINUTES * 60)


def _page(request: Request, template: str, build):
    """Render a page, or the download-progress page while the first download runs."""
    sync.start()
    status = sync.status()
    if not sync.has_core_data():
        return templates.TemplateResponse(request, "loading.html", {"status": status})
    lg = model.league()
    _track(lg)
    data = build(lg)
    if isinstance(data, RedirectResponse):
        return data
    return templates.TemplateResponse(request, template, {**data, "lg": lg, "status": status, "saved_out": saved_out(),
                                                                 "injury": injuries.player_notes(), "injury_status": injuries.status()})


def _rank(values: dict[int, float], tid: int, higher_better: bool = True) -> int:
    ordered = sorted(values, key=lambda k: -values[k] if higher_better else values[k])
    return ordered.index(tid) + 1


def _team_ratings(lg: model.League, out: set[int]) -> dict[int, dict]:
    avg = lg.league_avg()
    rows = {}
    for tid in lg.teams:
        s = lg.strength(tid, out)
        rows[tid] = {"off": avg["ortg"] + s["off"], "def": avg["ortg"] - s["def"], "net": s["off"] + s["def"], "pace": avg["pace"] + s["pace"]}
    for key, higher in (("off", True), ("def", False), ("net", True), ("pace", True)):
        values = {tid: r[key] for tid, r in rows.items()}
        for tid in rows:
            rows[tid][f"{key}_rank"] = _rank(values, tid, higher)
    return rows


def _record(lg: model.League, tid: int) -> tuple[str, str]:
    cur = lg.team_seasons[lg.cur].get(tid)
    if cur and cur.gp:
        return f"{cur.w}–{cur.l}", lg.cur
    prev = lg.team_seasons[lg.prev].get(tid)
    return (f"{prev.w}–{prev.l}", lg.prev) if prev else ("", "")


def _games(lg: model.League, team_id: int | None = None):
    df = lg.schedule
    if team_id is not None:
        df = df[(df["homeTeam_teamId"] == team_id) | (df["awayTeam_teamId"] == team_id)]
    return df


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    def build(lg):
        ratings = _team_ratings(lg, availability.now_out())
        now = datetime.now(config.TZ)
        conferences = {"East": [], "West": []}
        for tid, t in lg.teams.items():
            upcoming = _games(lg, tid)
            upcoming = upcoming[upcoming["gameStatus"] != 3]
            nxt = upcoming.iloc[0] if len(upcoming) else None
            record, record_season = _record(lg, tid)
            conferences[t["conference"]].append({
                "team": t, "rating": ratings[tid], "record": record, "record_season": record_season,
                "next": None if nxt is None else {
                    "opp": lg.teams[nxt["awayTeam_teamId"] if nxt["homeTeam_teamId"] == tid else nxt["homeTeam_teamId"]]["abbreviation"],
                    "home": nxt["homeTeam_teamId"] == tid,
                    "start": nxt["start"],
                },
            })
        for teams in conferences.values():
            teams.sort(key=lambda r: -r["rating"]["net"])
        return {"conferences": conferences, "now": now, "teams_sorted": sorted(lg.teams.values(), key=lambda t: t["full_name"])}
    return _page(request, "home.html", build)


def _side(lg: model.League, tid: int, score, names: list[str]) -> dict:
    record, record_season = _record(lg, tid)
    return {"team": lg.teams[tid], "record": record, "old_record": record_season != lg.cur, "score": score, "out": names}


@app.get("/today", response_class=HTMLResponse)
def today_page(request: Request, date: str | None = None):
    """One NZ day's games: live scores, predictions (the saved pre-game one once a game starts) and results."""
    def build(lg):
        now = datetime.now(config.TZ)
        games = lg.all_games[lg.all_games["homeTeam_teamId"].isin(lg.teams) & lg.all_games["awayTeam_teamId"].isin(lg.teams)]
        local_days = games["start"].dt.date
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date() if date else now.date()
        except ValueError:
            day = now.date()
        days = sorted(set(local_days))
        todays = games[local_days == day]
        # Live scores for games that have started but aren't final in the downloaded data.
        live = {}
        for us_date in {str(g.us_date) for g in todays.itertuples() if g.gameStatus != 3 and g.start <= now}:
            live.update(nba.scoreboard(us_date))
        records, own_lists, out_for = tracker.load(), availability.game_outs(), _out_for(lg)
        cards = []
        for g in todays.itertuples():
            h, a = g.homeTeam_teamId, g.awayTeam_teamId
            now_g = live.get(g.gameId, {})
            status = now_g.get("status", g.gameStatus)
            home_score = now_g.get("home", g.homeTeam_score)
            away_score = now_g.get("away", g.awayTeam_score)
            text = now_g.get("text") or g.gameStatusText
            rec = records.get(g.gameId)
            out = out_for(g.gameId, h, a)
            if status >= 2 and rec:   # started: the prediction saved before tip-off
                home_pts, away_pts, home_win, source = rec["home_pts"], rec["away_pts"], rec["home_win"], "saved"
            else:
                p = lg.predict(h, a, out, g.us_date, bool(g.isNeutral))
                home_pts, away_pts, home_win = p["home"]["pts"], p["away"]["pts"], p["home_win"]
                source = "now" if status == 1 else "untracked"
            names = {t: [lg.players[pid].name for pid in out if lg.players[pid].team_id == t] for t in (h, a)}
            card = {
                "id": g.gameId, "start": g.start, "status": status, "text": text, "label": g.gameSubLabel or g.gameLabel or "",
                "kind": tracker.KINDS.get(g.gameId[:3]), "away": _side(lg, a, away_score, names[a]), "home": _side(lg, h, home_score, names[h]),
                "home_pts": home_pts, "away_pts": away_pts, "home_win": home_win, "source": source,
                "saved_at": datetime.fromisoformat(rec["logged_at"]).astimezone(config.TZ) if rec else None,
                "own_list": g.gameId in own_lists,
            }
            if status == 3:
                card["home_won"] = home_score > away_score
                card["correct"] = (home_win >= 0.5) == card["home_won"]
                card["margin_miss"] = (home_pts - away_pts) - (home_score - away_score)
            cards.append(card)
        scored = [c for c in cards if c["status"] == 3 and c["source"] == "saved"]
        return {
            "day": day, "is_today": day == now.date(), "cards": cards, "now": now,
            "prev_day": max((d for d in days if d < day), default=None),
            "next_day": min((d for d in days if d > day), default=None),
            "live_count": sum(c["status"] == 2 for c in cards),
            "right": sum(c["correct"] for c in scored), "scored": len(scored),
            # Refresh every minute while a game is on or about to start.
            "refresh": any(c["status"] == 2 or (c["status"] == 1 and (c["start"] - now).total_seconds() < 900) for c in cards),
        }
    return _page(request, "today.html", build)


@app.get("/team/{abbr}", response_class=HTMLResponse)
def team_page(request: Request, abbr: str, season: str | None = None):
    def build(lg):
        tid = lg.by_abbr.get(abbr.upper())
        if tid is None:
            return RedirectResponse("/", status_code=303)
        out = availability.now_out()
        ratings = _team_ratings(lg, out)
        out_for, own_lists = _out_for(lg), availability.game_outs()
        upcoming, results = [], []
        for g in _games(lg, tid).itertuples():
            is_home = g.homeTeam_teamId == tid
            opp = g.awayTeam_teamId if is_home else g.homeTeam_teamId
            row = {"game_id": g.gameId, "start": g.start, "home": is_home, "opp": lg.teams[opp], "label": g.gameSubLabel or g.gameLabel or ""}
            if g.gameStatus == 3:
                mine, theirs = (g.homeTeam_score, g.awayTeam_score) if is_home else (g.awayTeam_score, g.homeTeam_score)
                results.append({**row, "pts": mine, "opp_pts": theirs, "won": mine > theirs})
            else:
                game_out = out_for(g.gameId, g.homeTeam_teamId, g.awayTeam_teamId)
                p = lg.predict(g.homeTeam_teamId, g.awayTeam_teamId, game_out, g.us_date, bool(g.isNeutral))
                me, them = (p["home"], p["away"]) if is_home else (p["away"], p["home"])
                win = p["home_win"] if is_home else 1 - p["home_win"]
                upcoming.append({**row, "pts": me["pts"], "opp_pts": them["pts"], "win": win, "live": g.gameStatus == 2, "b2b": me["b2b"],
                                 "own_list": g.gameId in own_lists, "out_names": [lg.players[i].name for i in game_out]})
        strength = lg.strength(tid, out)
        roster = sorted(lg.roster(tid), key=lambda p: -strength["minutes"].get(p.id, 0) - p.mpg / 100)
        record, record_season = _record(lg, tid)
        seasons = shots.shot_seasons()
        cur_played = (lg.team_seasons[lg.cur].get(tid) or model.TeamSeason()).gp > 0
        chosen = season if season in seasons else (lg.cur if cur_played else lg.prev)
        return {
            "team": lg.teams[tid], "rating": ratings[tid], "upcoming": upcoming, "results": list(reversed(results)),
            "roster": roster, "minutes": strength["minutes"], "record": record, "record_season": record_season,
            "offence_chart": _team_chart(tid, chosen, defence=False),
            "defence_chart": _team_chart(tid, chosen, defence=True),
            "shot_seasons": seasons, "shot_season": chosen,
        }
    return _page(request, "team.html", build)


@app.post("/unavailable")
def set_unavailable(player_id: int = Form(...), out: bool = Form(...), back: str = Form("/")):
    ids = saved_out()
    (ids.add if out else ids.discard)(player_id)
    _save_out(ids)
    return RedirectResponse(back if back.startswith("/") else "/", status_code=303)


@app.post("/injuries/check")
def check_injuries(back: str = Form("/today")):
    """Look for a new injury report now (the app also checks every 15 minutes by itself)."""
    if sync.has_core_data():
        _check_injuries(model.league(), force=True)
    return RedirectResponse(back if back.startswith("/") else "/today", status_code=303)


@app.post("/game-outs")
def save_game_outs(game_id: str = Form(...), out: str = Form(""), clear: str = Form(""), origin: str = Form("")):
    """Save who's out for one game (or clear its list, so it uses the all-games list again)."""
    lg = model.league()
    rows = lg.schedule[lg.schedule["gameId"] == game_id]
    if rows.empty:
        return RedirectResponse("/", status_code=303)
    g = next(rows.itertuples())
    roster_ids = availability.rosters(lg, g.homeTeam_teamId, g.awayTeam_teamId)
    availability.set_game_out(game_id, None if clear else _parse_ids(out) & roster_ids)
    return RedirectResponse(f"/game/{game_id}" + (f"?from={origin}" if origin.replace("-", "").isalnum() else ""), status_code=303)


@app.post("/unavailable/save")
def save_unavailable(team_ids: str = Form(...), out: str = Form(""), auto: str = Form(""), back: str = Form("/")):
    """Replace the saved list for these teams' players with the given ones. Players ticked only because the
    injury report has them out (`auto`) stay off your list, so they come back when the report clears them."""
    lg = model.league()
    teams = _parse_ids(team_ids)
    on_teams = {p.id for p in lg.players.values() if p.team_id in teams}
    old = saved_out()
    ticked = _parse_ids(out) & on_teams
    _save_out((old - on_teams) | (ticked - (_parse_ids(auto) - old)))
    return RedirectResponse(back if back.startswith("/") else "/", status_code=303)


def _matchup(lg: model.League, home_id: int, away_id: int, out_param: str | None, game=None, mu: str | None = None) -> dict:
    roster_ids = availability.rosters(lg, home_id, away_id)
    game_id = game.gameId if game is not None else None
    own_list = game_id is not None and game_id in availability.game_outs()
    # The real list for this game (its own, else the all-games list); ?out= previews a different one.
    saved = availability.out_for_game(lg, game_id, home_id, away_id)
    all_games = saved_out() & roster_ids
    report = availability.report_out(game_id) & roster_ids
    out = saved if out_param is None else _parse_ids(out_param) & roster_ids
    us_date = game.us_date if game is not None else None
    neutral = bool(game.isNeutral) if game is not None else False
    p = lg.predict(home_id, away_id, out, us_date, neutral, matchups=_parse_matchups(mu), with_matchups=True)
    sides = []
    for key in ("away", "home"):
        side = p[key]
        tid = side["id"]
        playing = {line["player"].id for line in side["players"]}
        others = sorted((pl for pl in lg.roster(tid) if pl.id not in playing), key=lambda pl: (pl.id not in out, -pl.mpg))
        evidence = [{"player": lg.players[pid], "seasons": lg.games_without(pid, tid)} for pid in out if lg.players[pid].team_id == tid]
        record, record_season = _record(lg, tid)
        cur = lg.team_seasons[lg.cur].get(tid)
        last10 = (cur.last10 if cur and cur.gp >= 5 else (lg.team_seasons[lg.prev].get(tid) or model.TeamSeason()).last10)
        avg = lg.league_avg()
        s = side["strength"]
        sides.append({
            **side, "key": key, "team": lg.teams[tid], "win": p["home_win"] if key == "home" else 1 - p["home_win"],
            "others": others, "evidence": evidence, "record": record, "record_season": record_season, "last10": last10,
            "ortg": avg["ortg"] + s["off"], "drtg": avg["ortg"] - s["def"], "net": s["off"] + s["def"], "pace": avg["pace"] + s["pace"],
        })
    return {
        "p": p, "sides": sides, "out": out, "saved": saved, "out_changed": out != saved, "own_list": own_list,
        "all_games_out": all_games, "report_out": report, "names": {pid: lg.players[pid].name for pid in roster_ids},
        "h2h": lg.head_to_head(home_id, away_id), "home_team": lg.teams[home_id], "away_team": lg.teams[away_id],
    }


def _game_trail(lg: model.League, g, origin: str | None) -> tuple[list[tuple[str, str]], str]:
    """Breadcrumbs for a game page, from where it was opened (?from=): a team's schedule (its abbreviation),
    "today" or "predictions". Without one, the home team's schedule. Returns (crumbs, nav item to highlight)."""
    if origin == "today":
        day = g.start.date()
        return [("Today", "/today"), (g.start.strftime("%a %-d %b"), f"/today?date={day.isoformat()}")], "/today"
    if origin == "predictions":
        return [("Predictions", "/predictions")], "/predictions"
    tid = lg.by_abbr.get((origin or "").upper())
    if tid not in (g.homeTeam_teamId, g.awayTeam_teamId):
        tid = g.homeTeam_teamId
    team = lg.teams[tid]
    return [("Teams", "/"), (team["nickname"], f"/team/{team['abbreviation']}"), ("Schedule", f"/team/{team['abbreviation']}")], "/"


@app.get("/game/{game_id}", response_class=HTMLResponse)
def game_page(request: Request, game_id: str, out: str | None = None, mu: str | None = None, origin: str | None = Query(None, alias="from")):
    def build(lg):
        rows = lg.schedule[lg.schedule["gameId"] == game_id]
        if rows.empty:
            return RedirectResponse("/", status_code=303)
        g = next(rows.itertuples())
        data = _matchup(lg, g.homeTeam_teamId, g.awayTeam_teamId, out, g, mu)
        box = lg.box_score(game_id) if g.gameStatus == 3 else {}
        trail, nav_here = _game_trail(lg, g, origin)
        return {**data, "game": g, "box": box, "kind": model.GAME_TYPES.get(game_id[:3], ""), "trail": trail, "nav_here": nav_here,
                "origin": origin or ""}
    return _page(request, "game.html", build)


@app.get("/matchup", response_class=HTMLResponse)
def matchup_page(request: Request, home: str = "", away: str = "", out: str | None = None, mu: str | None = None):
    def build(lg):
        h, a = lg.by_abbr.get(home.upper()), lg.by_abbr.get(away.upper())
        if h is None or a is None or h == a:
            return RedirectResponse("/", status_code=303)
        return {**_matchup(lg, h, a, out, mu=mu), "game": None, "box": {}, "kind": "Custom matchup"}
    return _page(request, "game.html", build)


def _team_chart(team_id: int, season: str, defence: bool) -> dict | None:
    try:
        return shots.chart(shots.team_season(team_id, season, defence))
    except Exception:  # e.g. a season before the franchise existed, or stats.nba.com unreachable
        return None


MIN_LISTED_POSS = 5  # without an opponent picked, smaller head-to-heads aren't listed


def _matchup_rows(m: matchups.Matchups, lg: model.League, player_id: int, opponent: int | None, guarding: bool) -> list[dict]:
    """Rows for the player page's matchup tables (sorted and filtered in the browser). With an opponent:
    every player on its roster, including ones he's never matched up with. Without: everyone he's
    matched up with since tracking began."""
    if opponent is not None:
        ids = [p.id for p in lg.roster(opponent) if p.id != player_id]
    else:
        # Everyone he's faced, minus pairs too small to say anything (under MIN_LISTED_POSS possessions).
        if guarding:
            ids = [s_ for s_ in m.by_defender.get(player_id, []) if m.possessions(s_, player_id) >= MIN_LISTED_POSS]
        else:
            ids = [d for d in m.by_shooter.get(player_id, []) if m.possessions(player_id, d) >= MIN_LISTED_POSS]
    names = _player_names()
    rows = []
    for other in ids:
        shooter, defender = (other, player_id) if guarding else (player_id, other)
        pl = lg.players.get(other)
        hist = m.history(shooter, defender)
        rate = m.rate.get(shooter)
        poss = hist["PARTIAL_POSS"] if hist else 0
        per100 = 100 * hist["PLAYER_PTS"] / poss if hist and poss else None
        rows.append({
            "id": other, "name": pl.name if pl else names.get(other, (f"Player {other}",))[0],
            "team": lg.teams[pl.team_id]["abbreviation"] if pl and pl.team_id else "",
            "position": pl.position if pl else "", "group": matchups.POSITION_GROUP.get(pl.position if pl else "", ""),
            "shooter": shooter, "defender": defender, "hist": hist, "rate": rate, "poss": poss, "per100": per100,
            "vs_usual": per100 - 100 * rate if per100 is not None and rate else None,
            "fg": hist["MATCHUP_FGM"] / hist["MATCHUP_FGA"] if hist and hist["MATCHUP_FGA"] else None,
            "fg3": hist["MATCHUP_FG3M"] / hist["MATCHUP_FG3A"] if hist and hist["MATCHUP_FG3A"] else None,
            "effect": 100 * m.effect(shooter, defender) if rate else None,
        })
    rows.sort(key=lambda r: -r["poss"])
    return rows


def _season_row(lg: model.League, pid: int) -> tuple[str | None, dict | None]:
    """The season a player's numbers come from (this one once he's played, else last) and his per-game line."""
    pl = lg.players.get(pid)
    if not pl:
        return None, None
    for season in (lg.cur, lg.prev):
        if pl.per_game.get(season):
            return season, pl.per_game[season]
    return None, None


def _player_summary(lg: model.League, m: matchups.Matchups, pid: int) -> dict | None:
    """One player's headline numbers, for the Players table and comparisons."""
    pl = lg.players.get(pid)
    if not pl:
        return None
    season, pg = _season_row(lg, pid)
    adv = {}
    if season:
        table = profile.season_table(lg, season)
        if pid in table.index:
            adv = table.loc[pid].to_dict()
    return {
        "id": pid, "player": pl, "name": pl.name, "team": lg.teams.get(pl.team_id), "position": pl.position,
        "group": matchups.POSITION_GROUP.get(pl.position, ""), "age": pl.age, "height": pl.height, "season": season,
        "gp": pl.gp.get(season, 0) if season else 0, "mpg": pg["MIN"] if pg else None,
        **{k: (pg[k] if pg else None) for k in ("PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV")},
        "ts": adv.get("TS_PCT"), "usg": adv.get("USG_PCT"), "ast_pct": adv.get("AST_PCT"),
        "impact": pl.impact, "impact_off": pl.impact_off, "impact_def": pl.impact_def,
        "def_rating": 100 * m.defender[pid] if pid in m.defender else None,
    }


@app.get("/players", response_class=HTMLResponse)
def players_page(request: Request):
    def build(lg):
        m = matchups.load(lg)
        rows = [r for r in (_player_summary(lg, m, p.id) for p in lg.players.values() if p.team_id) if r]
        rows.sort(key=lambda r: -(r["PTS"] or 0))
        return {"rows": rows, "teams_sorted": sorted(lg.teams.values(), key=lambda t: t["full_name"])}
    return _page(request, "players.html", build)


@app.get("/players/compare", response_class=HTMLResponse)
def compare_page(request: Request, a: int | None = None, b: int | None = None):
    def build(lg):
        m = matchups.load(lg)
        sides = []
        for pid in (a, b):
            if not pid:
                sides.append(None)
                continue
            data = profile.profile(lg, pid)
            seasons = list(dict.fromkeys(r["SEASON_ID"] for r in data["regular"] if r["SEASON_ID"] >= shots.nba.FIRST_SHOT_SEASON))[::-1]
            try:
                chart = shots.chart(shots.player_season(pid, seasons[0])) if seasons else None
            except Exception:
                chart = None
            sides.append({
                "id": pid, "info": data["info"], "data": data, "summary": _player_summary(lg, m, pid),
                "chart": chart, "chart_season": seasons[0] if seasons else None,
                "career": [(r["PLAYER_AGE"], r["SEASON_ID"], r["PTS"]) for r in data["regular"]
                           if r["TEAM_ABBREVIATION"] == "TOT" or sum(1 for x in data["regular"] if x["SEASON_ID"] == r["SEASON_ID"]) == 1],
            })
        h2h = None
        if a and b:
            h2h = {"a_vs_b": m.history(a, b), "b_vs_a": m.history(b, a), "est_ab": m.estimate(a, b), "est_ba": m.estimate(b, a)}
        return {"sides": sides, "h2h": h2h, "a": a, "b": b}
    return _page(request, "compare.html", build)


@app.get("/player/{player_id}")
def old_player_link(request: Request, player_id: int):
    """Player pages moved under /players."""
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/players/{player_id}{query}", status_code=301)


@app.get("/players/{player_id}", response_class=HTMLResponse)
def player_page(request: Request, player_id: int, season: str | None = None, vs: str | None = None):
    def build(lg):
        data = profile.profile(lg, player_id)
        pl = data["player"]
        opponent = lg.by_abbr.get((vs or "").upper())

        # Shot chart: any season of his career since 1996-97, or all of them combined.
        seasons = list(dict.fromkeys(r["SEASON_ID"] for r in data["regular"] if r["SEASON_ID"] >= shots.nba.FIRST_SHOT_SEASON))[::-1]
        chosen = season if season in seasons or (season == "career" and seasons) else (seasons[0] if seasons else None)
        chart, job, shot_error = None, None, None
        try:
            if chosen == "career":
                df, job = shots.career(player_id, seasons)
                chart = shots.chart(df, opponent) if df is not None else None
            elif chosen:
                chart = shots.chart(shots.player_season(player_id, chosen), opponent)
        except Exception as exc:
            shot_error = f"Couldn't download the shots: {type(exc).__name__}"

        m = matchups.load(lg)
        data.update(
            chart=chart, shot_seasons=seasons, shot_season=chosen, career_job=job, shot_error=shot_error,
            shot_vs=opponent, opponent_team=lg.teams.get(opponent),
            guarded_by=_matchup_rows(m, lg, player_id, opponent, guarding=False),
            guarding=_matchup_rows(m, lg, player_id, opponent, guarding=True),
            defender_rating=m.defender.get(player_id), tracking_since=m.first_season,
            teams_sorted=sorted(lg.teams.values(), key=lambda t: t["full_name"]),
        )
        team = lg.teams.get(pl.team_id) if pl and pl.team_id else None
        evidence = lg.games_without(player_id, pl.team_id) if team else []
        similar_season, similar = profile.similar(lg, player_id)
        return {**data, "team": team, "evidence": evidence, "similar": similar, "similar_season": similar_season}
    return _page(request, "player.html", build)


@app.get("/predictions", response_class=HTMLResponse)
def predictions_page(request: Request, kind: str | None = None, backfilled: int = 1):
    def build(lg):
        records = list(tracker.load().values())
        kinds = [k for k in ("reg", "post", "pre") if any(r["kind"] == k for r in records)]
        chosen = kind if kind in kinds else (kinds[0] if kinds else "reg")
        mine = [r for r in records if r["kind"] == chosen and (backfilled or not r.get("backfilled"))]
        rows = tracker.rows(mine, lg)
        # Finished games of this kind with no saved prediction: the app wasn't open before them.
        finished = lg.all_games[(lg.all_games["gameStatus"] == 3) & (lg.all_games["gameId"].str[:3].map(tracker.KINDS) == chosen)]
        untracked = int((~finished["gameId"].isin({r["game_id"] for r in records})).sum())
        return {
            "kinds": kinds, "kind": chosen, "labels": tracker.KIND_LABELS, "backfilled": backfilled,
            "has_backfilled": any(r.get("backfilled") for r in records if r["kind"] == chosen),
            "summary": tracker.summary(mine), "finished_rows": [r for r in rows if "result" in r],
            "upcoming_rows": sorted([r for r in rows if "result" not in r], key=lambda r: r["start"]),
            "untracked": untracked, "how_tracked": tracker.HOW_TRACKED,
            "days": sorted({r["start_local"].date() for r in rows}),
        }
    return _page(request, "predictions.html", build)


MISS_CHOICES = [(5, "Next 5 games"), (10, "Next 10 games"), (20, "Next 20 games"), (41, "Next 41 games"), (None, "Rest of season")]


def _parse_missing(text: str | None) -> dict[int, int | None]:
    """?miss=203999:20,1628983:rest -> {203999: 20, 1628983: None}"""
    out = {}
    for part in (text or "").split(","):
        pid, _, games = part.partition(":")
        if pid.strip().isdigit():
            out[int(pid)] = None if games.strip() in ("", "rest") else int(games) if games.strip().isdigit() else 10
    return out


@app.get("/simulator", response_class=HTMLResponse)
def simulator_page(request: Request, miss: str | None = None, saved: str = "10"):
    def build(lg):
        scenario = _parse_missing(miss)
        # Players on the saved unavailable list miss their next `saved` games (or the rest of the season).
        saved_games = None if saved == "rest" else int(saved) if saved.isdigit() else 10
        missing, outs = _sim_inputs(saved_games)
        if saved == "0":
            missing, outs = {}, availability.game_outs()
        missing.update(scenario)
        result = simulator.run(lg, missing, game_outs=outs)
        conferences = {c: sorted([t for t in result["teams"] if t["conference"] == c], key=lambda t: -t["wins"])
                       for c in ("East", "West")}
        names = _player_names()
        rows = [{"id": pid, "games": games, "player": lg.players.get(pid),
                 "name": lg.players[pid].name if pid in lg.players else names.get(pid, (str(pid),))[0]}
                for pid, games in scenario.items()]
        return {"result": result, "conferences": conferences, "scenario": rows, "miss": miss or "",
                "saved_choice": saved, "saved_count": len(availability.now_out()), "choices": MISS_CHOICES,
                "favourites": sorted(result["teams"], key=lambda t: -t["title"])[:5]}
    return _page(request, "simulator.html", build)


@app.get("/trades", response_class=HTMLResponse)
def trades_page(request: Request, a: str = "LAL", b: str = "OKC"):
    def build(lg):
        ta = lg.by_abbr.get(a.upper(), lg.by_abbr["LAL"])
        tb = lg.by_abbr.get(b.upper(), lg.by_abbr["OKC"])
        if ta == tb:
            tb = next(t for t in sorted(lg.teams) if t != ta)
        # Each ticked player goes to the other team.
        # The form sends one ?send= per ticked player (a link may also use send=1,2,3).
        ticked = set().union(*(_parse_ids(v) for v in request.query_params.getlist("send")))
        moves = {pid: (tb if lg.players[pid].team_id == ta else ta) for pid in ticked
                 if pid in lg.players and lg.players[pid].team_id in (ta, tb)}
        rosters = {t: sorted(lg.roster(t), key=lambda p: -p.mpg) for t in (ta, tb)}
        result = None
        if moves:
            after = lg.with_trade(moves)
            # Same assumption as the simulator's default: players out now miss their next 10 games.
            missing, outs = _sim_inputs(10)
            sims = simulator.run(lg, missing, game_outs=outs), simulator.run(after, missing, game_outs=outs)
            ratings = _team_ratings(lg, set()), _team_ratings(after, set())
            sides = []
            for t in (ta, tb):
                sim = [next(x for x in r["teams"] if x["team"]["id"] == t) for r in sims]
                rot_before, rot_after = lg.rotation(t, set()), after.rotation(t, set())
                names = {p.id: p.name for p in lg.players.values()}
                rotation = sorted({*rot_before, *rot_after}, key=lambda pid: -max(rot_before.get(pid, 0), rot_after.get(pid, 0)))
                sides.append({
                    "team": lg.teams[t], "before": ratings[0][t], "after": ratings[1][t], "sim": sim,
                    "gets": [lg.players[p] for p, dest in moves.items() if dest == t],
                    "sends": [lg.players[p] for p, dest in moves.items() if dest != t],
                    "rotation": [{"id": pid, "name": names.get(pid, str(pid)), "before": rot_before.get(pid, 0),
                                  "after": rot_after.get(pid, 0)} for pid in rotation],
                })
            result = {"sides": sides}
        return {"ta": lg.teams[ta], "tb": lg.teams[tb], "rosters": rosters, "sending": set(moves), "result": result,
                "teams_sorted": sorted(lg.teams.values(), key=lambda t: t["full_name"])}
    return _page(request, "trades.html", build)


@app.get("/matchup-detail", response_class=HTMLResponse)
def matchup_detail(request: Request, shooter: int, defender: int):
    """The popup: expected outcome when `defender` guards `shooter`, with their head-to-head if any."""
    lg = model.league()
    m = matchups.load(lg)
    est = m.estimate(shooter, defender)
    s_pl, d_pl = lg.players.get(shooter), lg.players.get(defender)
    # Possessions he'd be guarded by this defender in a game: his minutes x pace, times the primary share.
    mpg = s_pl.mpg if s_pl and s_pl.mpg else 30.0
    guarded = matchups.PRIMARY_SHARE * mpg / 48 * lg.league_avg()["pace"]
    names = _player_names()
    return templates.TemplateResponse(request, "_matchup_detail.html", {
        "shooter": s_pl, "defender": d_pl, "shooter_id": shooter, "defender_id": defender,
        "shooter_name": s_pl.name if s_pl else names.get(shooter, (f"Player {shooter}",))[0],
        "defender_name": d_pl.name if d_pl else names.get(defender, (f"Player {defender}",))[0],
        "est": est, "seasons": m.seasons(shooter, defender), "hist": m.history(shooter, defender),
        "guarded": guarded, "mpg": mpg, "lg": lg, "share": matchups.PRIMARY_SHARE, "tracking_since": m.first_season,
        "size_fg_per_inch": m.size_fg,
    })


def _fold(text: str) -> str:
    """Lower case without accents, so "doncic" finds Dončić."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


_PLAYER_NAMES = None


def _player_names() -> dict[int, tuple[str, str]]:
    """Every NBA player ever: id -> (name, folded name), from nba_api's built-in list."""
    global _PLAYER_NAMES
    if _PLAYER_NAMES is None:
        from nba_api.stats.static import players as static_players
        _PLAYER_NAMES = {p["id"]: (p["full_name"], _fold(p["full_name"])) for p in static_players.get_players()}
    return _PLAYER_NAMES


@app.get("/player-search")
def player_search(q: str = "", limit: int = 10):
    """Players whose name matches q, for the matchup search boxes. Only players with tracked matchups
    (2017-18 on) are useful there, so they come first, current players before retired ones."""
    lg = model.league()
    m = matchups.load(lg)
    words = _fold(q).split()
    if not words:
        return JSONResponse([])
    names = _player_names()
    for p in lg.players.values():  # rookies the built-in list may not have yet
        names.setdefault(p.id, (p.name, _fold(p.name)))
    hits = [pid for pid, (_, folded) in names.items() if all(w in folded for w in words)]
    tracked = lambda pid: pid in m.rate or pid in m.defender
    hits.sort(key=lambda pid: (not tracked(pid), not (lg.players.get(pid) and lg.players[pid].team_id),
                               not names[pid][1].startswith(words[0]), names[pid][0]))
    out = []
    for pid in hits[:limit]:
        pl = lg.players.get(pid)
        team = lg.teams[pl.team_id]["abbreviation"] if pl and pl.team_id else ""
        out.append({"id": pid, "name": names[pid][0], "team": team, "tracked": tracked(pid)})
    return JSONResponse(out)


@app.get("/phone", response_class=HTMLResponse)
def phone_page(request: Request):
    def build(lg):
        info = phone.status()
        names = {p.id: p.name for p in lg.players.values()}
        return {"phone": info, "now": time.time()}
    return _page(request, "phone.html", build)


@app.post("/phone/unpair")
def phone_unpair(phone_id: str = Form(...)):
    phone.unpair(phone_id)
    return RedirectResponse("/phone", status_code=303)


@app.post("/refresh")
def refresh(back: str = Form("/")):
    sync.start(force=True)
    return RedirectResponse(back if back.startswith("/") else "/", status_code=303)
