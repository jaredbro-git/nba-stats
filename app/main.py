import json
import time
from datetime import datetime

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, model, profile, sync


app = FastAPI(title="NBA")
app.mount("/static", StaticFiles(directory=config.BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=config.BASE_DIR / "app" / "templates")
templates.env.globals["asset_version"] = str(int(time.time()))
templates.env.globals["logo"] = lambda team_id: f"https://cdn.nba.com/logos/nba/{team_id}/global/L/logo.svg"
templates.env.globals["headshot"] = lambda pid: f"https://cdn.nba.com/headshots/nba/latest/260x190/{pid}.png"
templates.env.globals["height"] = lambda h: (
    f"{h.split('-')[0]}′{h.split('-')[1]}″ ({round(2.54 * (12 * int(h.split('-')[0]) + int(h.split('-')[1])))} cm)" if h and "-" in h else h
)
templates.env.filters["signed"] = lambda v, d=1: f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.{d}f}"
templates.env.filters["pct"] = lambda v, d=0: "–" if v is None else f"{100 * v:.{d}f}%"


# --- Players marked unavailable for every game (saved between visits) ---------

def saved_out() -> set[int]:
    try:
        return set(json.loads(config.UNAVAILABLE_FILE.read_text()))
    except (FileNotFoundError, ValueError):
        return set()


def _save_out(ids: set[int]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UNAVAILABLE_FILE.write_text(json.dumps(sorted(ids)))


def _parse_ids(text: str | None) -> set[int]:
    return {int(x) for x in (text or "").split(",") if x.strip().isdigit()}


# --- Pages ---------------------------------------------------------------------

def _page(request: Request, template: str, build):
    """Render a page, or the download-progress page while the first download runs."""
    sync.start()
    status = sync.status()
    if not sync.has_core_data():
        return templates.TemplateResponse(request, "loading.html", {"status": status})
    lg = model.league()
    data = build(lg)
    if isinstance(data, RedirectResponse):
        return data
    return templates.TemplateResponse(request, template, {**data, "lg": lg, "status": status, "saved_out": saved_out()})


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
        ratings = _team_ratings(lg, saved_out())
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


@app.get("/team/{abbr}", response_class=HTMLResponse)
def team_page(request: Request, abbr: str):
    def build(lg):
        tid = lg.by_abbr.get(abbr.upper())
        if tid is None:
            return RedirectResponse("/", status_code=303)
        out = saved_out()
        ratings = _team_ratings(lg, out)
        upcoming, results = [], []
        for g in _games(lg, tid).itertuples():
            is_home = g.homeTeam_teamId == tid
            opp = g.awayTeam_teamId if is_home else g.homeTeam_teamId
            row = {"game_id": g.gameId, "start": g.start, "home": is_home, "opp": lg.teams[opp], "label": g.gameSubLabel or g.gameLabel or ""}
            if g.gameStatus == 3:
                mine, theirs = (g.homeTeam_score, g.awayTeam_score) if is_home else (g.awayTeam_score, g.homeTeam_score)
                results.append({**row, "pts": mine, "opp_pts": theirs, "won": mine > theirs})
            else:
                p = lg.predict(g.homeTeam_teamId, g.awayTeam_teamId, out, g.us_date, bool(g.isNeutral))
                me, them = (p["home"], p["away"]) if is_home else (p["away"], p["home"])
                win = p["home_win"] if is_home else 1 - p["home_win"]
                upcoming.append({**row, "pts": me["pts"], "opp_pts": them["pts"], "win": win, "live": g.gameStatus == 2, "b2b": me["b2b"]})
        strength = lg.strength(tid, out)
        roster = sorted(lg.roster(tid), key=lambda p: -strength["minutes"].get(p.id, 0) - p.mpg / 100)
        record, record_season = _record(lg, tid)
        return {
            "team": lg.teams[tid], "rating": ratings[tid], "upcoming": upcoming, "results": list(reversed(results)),
            "roster": roster, "minutes": strength["minutes"], "record": record, "record_season": record_season,
        }
    return _page(request, "team.html", build)


@app.post("/unavailable")
def set_unavailable(player_id: int = Form(...), out: bool = Form(...), back: str = Form("/")):
    ids = saved_out()
    (ids.add if out else ids.discard)(player_id)
    _save_out(ids)
    return RedirectResponse(back if back.startswith("/") else "/", status_code=303)


@app.post("/unavailable/save")
def save_unavailable(team_ids: str = Form(...), out: str = Form(""), back: str = Form("/")):
    """Replace the saved list for these teams' players with the given ones."""
    lg = model.league()
    teams = _parse_ids(team_ids)
    on_teams = {p.id for p in lg.players.values() if p.team_id in teams}
    _save_out((saved_out() - on_teams) | (_parse_ids(out) & on_teams))
    return RedirectResponse(back if back.startswith("/") else "/", status_code=303)


def _matchup(lg: model.League, home_id: int, away_id: int, out_param: str | None, game=None) -> dict:
    roster_ids = {p.id for p in lg.players.values() if p.team_id in (home_id, away_id)}
    saved = saved_out() & roster_ids
    out = saved if out_param is None else _parse_ids(out_param) & roster_ids
    us_date = game.us_date if game is not None else None
    neutral = bool(game.isNeutral) if game is not None else False
    p = lg.predict(home_id, away_id, out, us_date, neutral)
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
        "p": p, "sides": sides, "out": out, "saved": saved, "out_changed": out != saved,
        "h2h": lg.head_to_head(home_id, away_id), "home_team": lg.teams[home_id], "away_team": lg.teams[away_id],
    }


@app.get("/game/{game_id}", response_class=HTMLResponse)
def game_page(request: Request, game_id: str, out: str | None = None):
    def build(lg):
        rows = lg.schedule[lg.schedule["gameId"] == game_id]
        if rows.empty:
            return RedirectResponse("/", status_code=303)
        g = next(rows.itertuples())
        data = _matchup(lg, g.homeTeam_teamId, g.awayTeam_teamId, out, g)
        box = lg.box_score(game_id) if g.gameStatus == 3 else {}
        return {**data, "game": g, "box": box, "kind": model.GAME_TYPES.get(game_id[:3], "")}
    return _page(request, "game.html", build)


@app.get("/matchup", response_class=HTMLResponse)
def matchup_page(request: Request, home: str = "", away: str = "", out: str | None = None):
    def build(lg):
        h, a = lg.by_abbr.get(home.upper()), lg.by_abbr.get(away.upper())
        if h is None or a is None or h == a:
            return RedirectResponse("/", status_code=303)
        return {**_matchup(lg, h, a, out), "game": None, "box": {}, "kind": "Custom matchup"}
    return _page(request, "game.html", build)


@app.get("/player/{player_id}", response_class=HTMLResponse)
def player_page(request: Request, player_id: int):
    def build(lg):
        data = profile.profile(lg, player_id)
        pl = data["player"]
        team = lg.teams.get(pl.team_id) if pl and pl.team_id else None
        evidence = lg.games_without(player_id, pl.team_id) if team else []
        return {**data, "team": team, "evidence": evidence}
    return _page(request, "player.html", build)


@app.post("/refresh")
def refresh(back: str = Form("/")):
    sync.start(force=True)
    return RedirectResponse(back if back.startswith("/") else "/", status_code=303)
