"""Shot charts: hexagon heat maps and zone breakdowns for a player, a team's offence or a team's defence.

Shots are downloaded when a chart is first opened (one request per player-season or team-season,
back to 1996-97) and kept; the current season is refreshed with the rest of its data. Each shot is
compared with that season's league FG% in the same court zone, so colour shows shooting above or
below league average for those spots, and hexagon size shows how often shots come from there.
"""

import math
import threading

import numpy as np
import pandas as pd
from markupsafe import Markup
from nba_api.stats.static import teams as static_teams

from . import config, nba

TEAM_ID = {t["abbreviation"]: t["id"] for t in static_teams.get_teams()}
# Abbreviations the shot data uses for franchises that have since moved or been renamed.
OLD_ABBR = {"NJN": "BKN", "SEA": "OKC", "VAN": "MEM", "CHH": "CHA", "NOH": "NOP", "NOK": "NOP", "WSB": "WAS",
            "PHO": "PHX", "GOS": "GSW", "SAN": "SAS", "UTH": "UTA"}

# Court drawing: NBA shot coordinates are tenths of a foot from the basket (x across, y toward
# half court). The chart shows y from -52 to 348 (40 ft) with the basket near the bottom.
VIEW_W, VIEW_H, Y_TOP = 500, 400, 348
HEX_R = 15            # hexagon radius: 1.5 ft
SHRINK = 6            # pseudo-shots toward league average, so a 2-for-2 hexagon isn't "red hot"
STEPS = (0.015, 0.04, 0.07, 0.10)  # colour steps: FG% points above/below league

ZONE_LABELS = ["Restricted area", "Paint (non-restricted)", "Mid-range", "Left corner 3", "Right corner 3",
               "Above-the-break 3"]  # in nba.ZONE_BASIC order; backcourt heaves are left out of the table

_cache: dict = {}


def _svg(x: float, y: float) -> tuple[float, float]:
    return x + VIEW_W / 2, Y_TOP - y


def _franchise(abbr: str) -> int | None:
    return TEAM_ID.get(OLD_ABBR.get(abbr, abbr))


def _prepare(key: str, frames: list[pd.DataFrame], defence_of: int | None = None) -> pd.DataFrame:
    """Adds each shot's expected FG% (league, same zone and season) and the opponent's franchise id."""
    path = config.CACHE_DIR / f"{key}.json"
    sig = path.stat().st_mtime if path.exists() else None
    if key in _cache and _cache[key][0] == sig:
        return _cache[key][1]
    df, zones = frames[0].copy(), frames[1]
    league = {(r.ZB, r.ZA, r.ZR): r.FGM / r.FGA for r in zones.itertuples() if r.FGA}
    df["EXP"] = [league.get(k, 0.0) for k in zip(df["ZB"], df["ZA"], df["ZR"])]
    if defence_of is not None:
        df["OPP_ID"] = defence_of
    elif len(df):
        # A team's own abbreviation is the one in every one of its rows (opponents vary).
        own = {tid: pd.concat([g["HTM"], g["VTM"]]).mode().iat[0] for tid, g in df.groupby("TEAM_ID")}
        own_abbr = df["TEAM_ID"].map(own)
        df["OPP_ID"] = df["VTM"].where(df["HTM"] == own_abbr, df["HTM"]).map(_franchise)
    else:
        df["OPP_ID"] = pd.Series(dtype=float)
    _cache[key] = (sig, df)
    return df


def player_season(player_id: int, season: str) -> pd.DataFrame:
    return _prepare(f"pshots_{player_id}_{season}", nba.player_shots(player_id, season))


def team_season(team_id: int, season: str, defence: bool = False) -> pd.DataFrame:
    key = f"{'d' if defence else 't'}shots_{team_id}_{season}"
    return _prepare(key, nba.team_shots(team_id, season, defence), defence_of=team_id if defence else None)


def is_cached(player_id: int, season: str) -> bool:
    return nba.cached_at(f"pshots_{player_id}_{season}") is not None


def shot_seasons(first: str | None = None) -> list[str]:
    """Seasons with shot data, newest first: from 1996-97 (or `first`) to the current one."""
    start = max(int(nba.FIRST_SHOT_SEASON[:4]), int(first[:4]) if first else 0)
    return [config.season_label(y) for y in range(int(config.current_season()[:4]), start - 1, -1)]


# --- Career charts: one request per season, downloaded in the background ---------------

_jobs: dict[int, dict] = {}
_jobs_lock = threading.Lock()


def career(player_id: int, seasons: list[str]) -> tuple[pd.DataFrame | None, dict | None]:
    """All of a player's seasons combined, or (None, progress) while missing seasons download."""
    missing = [s for s in seasons if not is_cached(player_id, s)]
    if not missing:
        frames = [player_season(player_id, s) for s in seasons]
        return pd.concat(frames, ignore_index=True), None
    with _jobs_lock:
        job = _jobs.get(player_id)
        if not job or not job["running"]:
            job = {"running": True, "done": len(seasons) - len(missing), "total": len(seasons), "error": None}
            _jobs[player_id] = job
            threading.Thread(target=_download, args=(player_id, missing, job), daemon=True).start()
    return None, job


def _download(player_id: int, seasons: list[str], job: dict) -> None:
    try:
        for s in seasons:
            nba.player_shots(player_id, s)
            job["done"] += 1
    except Exception as exc:
        job["error"] = f"{type(exc).__name__}: {exc}"[:200]
    finally:
        job["running"] = False


def _hex_points(cx: float, cy: float, r: float) -> str:
    pts = []
    for i in range(6):
        a = math.radians(60 * i - 30)  # pointy-top hexagon
        pts.append(f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}")
    return " ".join(pts)


def _bucket(diff: float) -> str:
    """CSS class for a FG% difference from league: c4…c1 (cold), mid, h1…h4 (hot)."""
    for i, step in reversed(list(enumerate(STEPS, start=1))):
        if diff >= step:
            return f"h{i}"
        if diff <= -step:
            return f"c{i}"
    return "mid"


def _hexes(df: pd.DataFrame) -> list[dict]:
    shown = df[(df["Y"] < Y_TOP) & (df["X"].abs() <= 250)]
    if shown.empty:
        return []
    x, y = shown["X"].to_numpy(dtype=float), shown["Y"].to_numpy(dtype=float)
    # Axial hex coordinates (pointy-top), rounded to the nearest hexagon via cube coordinates.
    q = (math.sqrt(3) / 3 * x - y / 3) / HEX_R
    r = (2 / 3 * y) / HEX_R
    s_ = -q - r
    rq, rr, rs = np.round(q), np.round(r), np.round(s_)
    dq, dr, ds = np.abs(rq - q), np.abs(rr - r), np.abs(rs - s_)
    fix_q = (dq > dr) & (dq > ds)
    fix_r = ~fix_q & (dr > ds)
    rq = np.where(fix_q, -rr - rs, rq)
    rr = np.where(fix_r, -rq - rs, rr)
    grouped = (
        shown.assign(HQ=rq.astype(int), HR=rr.astype(int))
        .groupby(["HQ", "HR"])
        .agg(fga=("MADE", "size"), fgm=("MADE", "sum"), exp=("EXP", "sum"), zone=("ZB", lambda z: z.mode().iat[0]))
        .reset_index()
    )
    cap = max(1.0, float(grouped["fga"].quantile(0.95)))
    out = []
    for g in grouped.itertuples():
        hx = HEX_R * math.sqrt(3) * (g.HQ + g.HR / 2)
        hy = HEX_R * 1.5 * g.HR
        sx, sy = _svg(hx, hy)
        size = HEX_R * (0.32 + 0.68 * math.sqrt(min(1.0, g.fga / cap)))
        diff = (g.fgm - g.exp) / (g.fga + SHRINK)
        zone = ZONE_LABELS[g.zone] if 0 <= g.zone < len(ZONE_LABELS) else "Backcourt"
        out.append({
            "points": _hex_points(sx, sy, size), "cls": _bucket(diff), "fga": int(g.fga), "fgm": int(g.fgm),
            "pct": g.fgm / g.fga, "league": g.exp / g.fga, "zone": zone,
        })
    return sorted(out, key=lambda h: h["fga"])  # big hexagons drawn last, on top


def _zones(df: pd.DataFrame) -> list[dict]:
    total = len(df)
    rows = []
    for code, label in enumerate(ZONE_LABELS):
        z = df[df["ZB"] == code]
        if z.empty:
            continue
        fga, fgm, exp = len(z), int(z["MADE"].sum()), float(z["EXP"].sum())
        rows.append({"label": label, "fga": fga, "share": fga / total, "pct": fgm / fga, "league": exp / fga,
                     "diff": (fgm - exp) / fga, "cls": _bucket((fgm - exp) / (fga + SHRINK))})
    return rows


def chart(df: pd.DataFrame | None, opponent_id: int | None = None) -> dict:
    """Heat map, zones and summary for a set of shots, optionally only those against one team."""
    if df is not None and opponent_id is not None:
        df = df[df["OPP_ID"] == opponent_id]
    if df is None or df.empty:
        return {"fga": 0, "hexes": [], "zones": []}
    fga = len(df)
    fgm = int(df["MADE"].sum())
    threes = df["IS3"] == 1
    efg = (fgm + 0.5 * int(df.loc[threes, "MADE"].sum())) / fga
    return {
        "fga": fga, "fgm": fgm, "pct": fgm / fga, "league": float(df["EXP"].sum()) / fga,
        "efg": efg, "three_share": float(threes.mean()), "games": int(df["GAME_ID"].nunique()),
        "hexes": _hexes(df), "zones": _zones(df),
    }


def court_svg() -> Markup:
    """Half-court lines (basket at the bottom) as SVG elements, drawn over the hexagons."""
    def p(x, y):
        sx, sy = _svg(x, y)
        return f"{sx:.1f} {sy:.1f}"

    corner_y = math.sqrt(237.5 ** 2 - 220 ** 2)
    parts = [
        f'<path d="M {p(-250, -47.5)} L {p(250, -47.5)}"/>',                         # baseline
        f'<path d="M {p(-80, -47.5)} L {p(-80, 142.5)} L {p(80, 142.5)} L {p(80, -47.5)}"/>',  # lane
        f'<path d="M {p(-60, -47.5)} L {p(-60, 142.5)} M {p(60, -47.5)} L {p(60, 142.5)}"/>',
        f'<path d="M {p(-60, 142.5)} A 60 60 0 0 1 {p(60, 142.5)}"/>',              # free-throw circle, top half
        f'<path d="M {p(-60, 142.5)} A 60 60 0 0 0 {p(60, 142.5)}" stroke-dasharray="6 6"/>',
        f'<path d="M {p(-40, 0)} A 40 40 0 0 1 {p(40, 0)}"/>',                        # restricted area
        f'<path d="M {p(-30, -7.5)} L {p(30, -7.5)}"/>',                              # backboard
        f'<circle cx="{_svg(0, 0)[0]}" cy="{_svg(0, 0)[1]}" r="7.5"/>',               # rim
        f'<path d="M {p(-220, -47.5)} L {p(-220, corner_y)} A 237.5 237.5 0 0 1 {p(220, corner_y)} L {p(220, -47.5)}"/>',
    ]
    return Markup("".join(parts))
