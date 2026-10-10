"""Player profile: bio, career by team, recent games, shot zones and a playstyle summary.

The NBA has no written playstyle descriptions, so the summary is built from where a player
ranks among regular rotation players (500+ minutes) on usage, playmaking, shot locations,
rebounding and defensive events.
"""

from datetime import datetime

import pandas as pd

from . import nba
from .model import League

QUALIFY_MIN = 500
ZONES = [
    ("Restricted Area", "At the rim"),
    ("In The Paint (Non-RA)", "Paint (non-rim)"),
    ("Mid-Range", "Mid-range"),
    ("Corner 3", "Corner 3"),
    ("Above the Break 3", "Above-the-break 3"),
]


def _season_for(lg: League, pid: int) -> str | None:
    """The season the profile's playstyle is based on: this one after 10 games, else last."""
    pl = lg.players.get(pid)
    if pl and pl.gp.get(lg.cur, 0) >= 10:
        return lg.cur
    if pl and pl.gp.get(lg.prev):
        return lg.prev
    return lg.cur if pl and pl.gp.get(lg.cur) else None


def _pct_rank(series: pd.Series, value: float) -> float:
    return float((series < value).mean())


def _season_table(lg: League, season: str) -> pd.DataFrame:
    """Per-player season numbers used for league percentiles."""
    logs = lg.plogs[season]
    tot = logs.groupby("PLAYER_ID")[["MIN", "FGA", "FG3A", "FG3M", "FTA", "STL", "BLK", "AST", "TOV", "PTS"]].sum()
    tot["GP"] = logs.groupby("PLAYER_ID").size()
    adv_frames = nba.load(f"advanced_{season}")
    if adv_frames:
        adv = adv_frames[0].set_index("PLAYER_ID")[["USG_PCT", "AST_PCT", "OREB_PCT", "DREB_PCT", "TS_PCT", "AST_TO"]]
        tot = tot.join(adv, how="left")
    zone_frames = nba.load(f"shotzones_{season}")
    if zone_frames:
        z = zone_frames[0].set_index("PLAYER_ID")
        for key, _ in ZONES:
            tot[f"{key} FGA"] = z[f"{key} FGA"]
            tot[f"{key} FGM"] = z[f"{key} FGM"]
    for k in ("STL", "BLK", "FG3A"):
        tot[f"{k}36"] = 36 * tot[k] / tot["MIN"].where(tot["MIN"] > 0)
    tot["FTR"] = tot["FTA"] / tot["FGA"].where(tot["FGA"] > 0)
    tot["THREE_SHARE"] = tot["FG3A"] / tot["FGA"].where(tot["FGA"] > 0)
    return tot


def _traits(row: pd.Series, q: pd.DataFrame) -> list[dict]:
    def pct(col):
        return _pct_rank(q[col].dropna(), row[col]) if col in row and pd.notna(row[col]) else None

    def top(p):
        return f"top {max(1, round(100 * (1 - p)))}% of rotation players"

    traits = []
    if (p := pct("USG_PCT")) is not None and p >= 0.75:
        label = "Primary scorer" if p >= 0.9 else "Go-to scoring option"
        traits.append({"label": label, "detail": f"Uses {row['USG_PCT']:.0%} of team plays while on court ({top(p)})"})
    if (p := pct("AST_PCT")) is not None and p >= 0.75:
        label = "Lead playmaker" if p >= 0.9 else "Secondary playmaker"
        traits.append({"label": label, "detail": f"Assists on {row['AST_PCT']:.0%} of teammates' baskets while on court ({top(p)})"})
    if (p := pct("FG3A36")) is not None and p >= 0.75:
        made = row["FG3M"] / row["FG3A"] if row["FG3A"] else 0
        label = "High-volume 3-point shooter" if p >= 0.9 else "Floor spacer"
        traits.append({"label": label, "detail": f"{row['FG3A36']:.1f} threes per 36 minutes at {made:.1%} ({top(p)})"})
    fga = row.get("Restricted Area FGA", 0) + row.get("In The Paint (Non-RA) FGA", 0) + row.get("Mid-Range FGA", 0) + row.get("Corner 3 FGA", 0) + row.get("Above the Break 3 FGA", 0)
    if fga and fga >= 100:
        rim = row["Restricted Area FGA"] / fga
        mid = row["Mid-Range FGA"] / fga
        corner = row["Corner 3 FGA"] / max(1, row["Corner 3 FGA"] + row["Above the Break 3 FGA"])
        if rim >= 0.45:
            rim_pct = row["Restricted Area FGM"] / row["Restricted Area FGA"]
            traits.append({"label": "Rim finisher", "detail": f"{rim:.0%} of shots at the rim, made at {rim_pct:.0%}"})
        if mid >= 0.2:
            mid_pct = row["Mid-Range FGM"] / row["Mid-Range FGA"]
            traits.append({"label": "Mid-range shot-maker", "detail": f"{mid:.0%} of shots from mid-range, made at {mid_pct:.0%}"})
        if corner >= 0.4 and row["FG3A"] >= 100:
            traits.append({"label": "Corner specialist", "detail": f"{corner:.0%} of threes come from the corners"})
    if (p := pct("FTR")) is not None and p >= 0.85:
        traits.append({"label": "Draws fouls", "detail": f"{row['FTR']:.2f} free throws per shot ({top(p)})"})
    if (p := pct("TS_PCT")) is not None and p >= 0.85 and row["PTS"] / row["GP"] >= 10:
        traits.append({"label": "Efficient scorer", "detail": f"{row['TS_PCT']:.1%} true shooting ({top(p)})"})
    if (p := pct("OREB_PCT")) is not None and p >= 0.85:
        traits.append({"label": "Offensive rebounder", "detail": f"Grabs {row['OREB_PCT']:.0%} of available offensive rebounds ({top(p)})"})
    if (p := pct("DREB_PCT")) is not None and p >= 0.85:
        traits.append({"label": "Defensive rebounder", "detail": f"Grabs {row['DREB_PCT']:.0%} of available defensive rebounds ({top(p)})"})
    if (p := pct("BLK36")) is not None and p >= 0.85:
        traits.append({"label": "Rim protector", "detail": f"{row['BLK36']:.1f} blocks per 36 minutes ({top(p)})"})
    if (p := pct("STL36")) is not None and p >= 0.85:
        traits.append({"label": "Active hands", "detail": f"{row['STL36']:.1f} steals per 36 minutes ({top(p)})"})
    if "AST_TO" in row and pd.notna(row["AST_TO"]) and row["AST_TO"] >= 3 and row["AST"] / row["GP"] >= 3:
        traits.append({"label": "Low turnover", "detail": f"{row['AST_TO']:.1f} assists per turnover"})
    return traits


def _summary(name: str, position: str, traits: list[dict], mpg: float) -> str:
    role = "starter" if mpg >= 28 else "rotation player" if mpg >= 16 else "bench player"
    pos = {"G": "guard", "F": "forward", "C": "centre", "G-F": "wing", "F-G": "wing", "F-C": "big", "C-F": "big"}.get(position, "")
    words = [t["label"].lower() for t in traits[:3]]
    if not words:
        return f"{name} is a {pos} {role} ({mpg:.0f} minutes a game) without a stat profile that stands out from the league.".replace("  ", " ")
    listed = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
    return f"{name} is a {pos} {role} ({mpg:.0f} minutes a game): {listed}.".replace("  ", " ")


def _zones(row: pd.Series, q: pd.DataFrame) -> list[dict]:
    total = sum(row.get(f"{k} FGA", 0) or 0 for k, _ in ZONES)
    if not total:
        return []
    out = []
    for key, label in ZONES:
        fga, fgm = row[f"{key} FGA"], row[f"{key} FGM"]
        league_pct = q[f"{key} FGM"].sum() / q[f"{key} FGA"].sum()
        out.append({"label": label, "share": fga / total, "fga": fga, "pct": fgm / fga if fga else None, "league_pct": league_pct})
    return out


def profile(lg: League, pid: int) -> dict:
    info_df = nba.player_info(pid)
    info = info_df.iloc[0].to_dict() if len(info_df) else {}
    regular, playoffs = nba.career(pid)
    pl = lg.players.get(pid)

    # Past teams in order, each with the seasons played there.
    teams = []
    for r in regular[regular["TEAM_ABBREVIATION"] != "TOT"].itertuples():
        if teams and teams[-1]["abbr"] == r.TEAM_ABBREVIATION:
            teams[-1]["to"] = r.SEASON_ID
            teams[-1]["gp"] += r.GP
        else:
            teams.append({"abbr": r.TEAM_ABBREVIATION, "team_id": r.TEAM_ID, "from": r.SEASON_ID, "to": r.SEASON_ID, "gp": r.GP})

    season = _season_for(lg, pid)
    traits, zones, summary, style_row = [], [], None, None
    if season:
        table = _season_table(lg, season)
        q = table[table["MIN"] >= QUALIFY_MIN]
        if pid in table.index:
            style_row = table.loc[pid]
            traits = _traits(style_row, q)
            zones = _zones(style_row, q)
            mpg = style_row["MIN"] / style_row["GP"]
            summary = _summary(info.get("DISPLAY_FIRST_LAST", pl.name if pl else ""), info.get("POSITION", "") and _short_pos(info["POSITION"]), traits, mpg)

    recent = pd.DataFrame()
    for s in (lg.cur, lg.prev):
        logs = lg.plogs[s]
        if not logs.empty and (mine := logs[logs["PLAYER_ID"] == pid]).shape[0]:
            recent = mine.sort_values("GAME_DATE", ascending=False).head(10)
            recent_season = s
            break
    else:
        recent_season = None

    birth = info.get("BIRTHDATE")
    age = None
    if birth:
        b = datetime.fromisoformat(birth[:10]).date()
        today = datetime.now().date()
        age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))

    return {
        "info": info,
        "player": pl,
        "age": age,
        "teams": teams,
        "regular": regular.to_dict("records"),
        "playoffs": playoffs.to_dict("records"),
        "style_season": season,
        "traits": traits,
        "zones": zones,
        "summary": summary,
        "recent": recent.to_dict("records"),
        "recent_season": recent_season,
    }


def _short_pos(position: str) -> str:
    return {"Guard": "G", "Forward": "F", "Center": "C", "Guard-Forward": "G-F", "Forward-Guard": "F-G",
            "Forward-Center": "F-C", "Center-Forward": "C-F"}.get(position, "")
