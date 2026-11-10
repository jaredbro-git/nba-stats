"""The NBA's official injury report (official.nba.com): who's out for each game, read automatically.

The league publishes a PDF every 15 minutes or so on game days, listing every player on the day's teams who
is Out, Doubtful, Questionable, Probable or Available. check() finds the newest one, reads its table and
merges it into injuries.json:

- games: game id -> {player id: status} for every game in the report (each new report replaces its games).
- players: each player's latest status. A team in a new report has its players replaced by that report's
  list, so someone who's no longer listed is cleared; teams not in it keep their last statuses.

For a real prediction (availability.out_for_game), a game in the report uses the report's Out and Doubtful
players; a later game uses players whose latest status is Out with an injury ("carried forward" until their
team's next report clears them). G League assignments and two-way players are ignored: they aren't part of
the rotation anyway.
"""

import io
import json
import re
import threading
import time
import traceback
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from . import config

INDEX_URL = "https://official.nba.com/nba-injury-report-{season}-season/"
CHECK_MINUTES = 15
CATCH_UP_DAYS = 7
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"}
ET = ZoneInfo("America/New_York")
OUT_STATUSES = {"Out", "Doubtful"}   # counted out for a game in the report
STATUSES = ("Out", "Doubtful", "Questionable", "Probable", "Available")

# Column left edges in the PDF (points from the left), from the header row.
COLUMNS = [(0, "date"), (115, "time"), (195, "matchup"), (260, "team"), (420, "player"), (580, "status"), (660, "reason")]

_lock = threading.Lock()
_status = {"checking": False, "error": None}


def _file():
    return config.DATA_DIR / "injuries.json"


def load() -> dict:
    try:
        return json.loads(_file().read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _save(data: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(_file())


def fold(text: str) -> str:
    """Lowercase, no accents or punctuation: 'Nikola Jokić' and 'Jokic, Nikola' compare equal word by word."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


# --- Reading the PDF ---------------------------------------------------------------

def parse(pdf: bytes) -> list[dict]:
    """The report's rows: {date, matchup, team, player ('Last, First'), status, reason}.
    Date, matchup and team are only printed on the first row they apply to (even across pages), so they carry down."""
    import pypdf

    words = []   # (page, y, x, text)
    for n, page in enumerate(pypdf.PdfReader(io.BytesIO(pdf)).pages):
        def visit(text, cm, tm, font, size, n=n):
            if text.strip():
                words.append((n, tm[5], tm[4], text.strip()))
        page.extract_text(visitor_text=visit)

    def column(x):
        return [name for edge, name in COLUMNS if x >= edge - 3][-1]

    # Group words into lines (same page, y within 2 points), then cells by column.
    lines = []
    for n, y, x, text in sorted(words, key=lambda w: (w[0], w[1], w[2])):
        if lines and lines[-1]["page"] == n and abs(lines[-1]["y"] - y) <= 2:
            line = lines[-1]
        else:
            line = {"page": n, "y": y, "cells": {}}
            lines.append(line)
        line["cells"].setdefault(column(x), []).append(text)

    rows, ctx, loose = [], {"date": None, "matchup": None, "team": None}, []
    for line in lines:
        cells = {k: " ".join(v).replace(" ,", ",") for k, v in line["cells"].items()}
        text = " ".join(cells.values())
        if cells.get("date", "").startswith("Game") or text.startswith("Page") or text.startswith("Injury Report"):
            continue   # page header, title or page number
        if re.match(r"\d\d/\d\d/\d{4}", cells.get("date", "")):
            ctx["date"] = cells["date"][:10]
        if re.match(r"[A-Z]{2,3}@[A-Z]{2,3}", cells.get("matchup", "")):
            ctx["matchup"] = cells["matchup"].split()[0]
        if "team" in cells:
            ctx["team"] = cells["team"]
        status = next((s for s in STATUSES if cells.get("status", "").startswith(s)), None)
        if "player" in cells and "," in cells["player"] and status:
            rows.append({**ctx, "player": cells["player"], "status": status, "reason": [(line["y"], cells.get("reason", ""))],
                         "page": line["page"], "y": line["y"]})
        elif "reason" in cells and "player" not in cells and "NOT YET SUBMITTED" not in cells["reason"]:
            loose.append((line["page"], line["y"], cells["reason"]))
    # A long reason wraps onto lines above and below its player's line (or onto the top of the next page):
    # give each loose line to the nearest player.
    for page, y, text in loose:
        near = min((r for r in rows if r["page"] == page), key=lambda r: abs(r["y"] - y), default=None)
        if near is not None and abs(near["y"] - y) < 20:
            near["reason"].append((y, text))
        elif near is None or y < near["y"]:
            before = [r for r in rows if r["page"] < page]
            if before:
                before[-1]["reason"].append((10_000 + y, text))
    for r in rows:
        reason = " ".join(t for _, t in sorted(r.pop("reason")) if t)
        reason = re.sub(r"(\w)- (\w)", r"\1-\2", reason)   # a hyphenated word split over two pieces ("Two- Way")
        reason = re.sub(r"\s+-\s*|\s*-\s+", " - ", reason).replace("Injury/Illness - ", "").strip()
        r["reason"] = "" if reason == "-" else reason
        del r["page"], r["y"]
    return rows


def report_time(url: str) -> datetime | None:
    """When a report was published, from its file name (Injury-Report_2026-10-29_04_30PM.pdf, US Eastern)."""
    m = re.search(r"(\d{4}-\d\d-\d\d)_(\d\d)(?:_(\d\d))?([AP]M)", url)
    if not m:
        return None
    day, hour, minute, half = m.groups()
    t = datetime.strptime(f"{day} {hour}:{minute or '00'} {half}", "%Y-%m-%d %I:%M %p")
    return t.replace(tzinfo=ET).astimezone(timezone.utc)


def report_urls() -> list[str]:
    """Every report this season, oldest first."""
    html = requests.get(INDEX_URL.format(season=config.current_season()), headers=HEADERS, timeout=20).text
    urls = set(re.findall(r"https://ak-static\.cms\.nba\.com/referee/injury/Injury-Report_[^\"']+?\.pdf", html))
    return sorted((u for u in urls if report_time(u)), key=report_time)


REPORT_URL = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{day}_{time}.pdf"
LATE_TIMES = ("11_45PM", "11_30PM", "11_00PM", "08_00PM", "05_00PM")   # tried in turn for a past day's last report


def _last_report_of(day) -> str | None:
    """A past day's last report. The index page only lists today's, but older ones stay at the same addresses."""
    for t in LATE_TIMES:
        url = REPORT_URL.format(day=day.isoformat(), time=t)
        if requests.head(url, headers=HEADERS, timeout=15).status_code == 200:
            return url
    return None


def _to_read(urls: list[str], since: datetime | None) -> list[str]:
    """The reports to read after `since` (the last one read): the last report of each earlier US day, then the
    newest. With nothing read yet, the past week's, so every team's latest list is known even if it hasn't
    played today; after the Mac has been asleep, the days it missed."""
    now = datetime.now(timezone.utc)
    since = max(since or now - timedelta(days=CATCH_UP_DAYS), now - timedelta(days=CATCH_UP_DAYS))
    today = now.astimezone(ET).date()
    day, todo = since.astimezone(ET).date(), []
    while day < today:
        url = _last_report_of(day)
        if url and report_time(url) > since:
            todo.append(url)
        day += timedelta(days=1)
    todo += [u for u in urls[-1:] if report_time(u) > since]
    return todo


# --- Matching names to players and games ----------------------------------------------

def _match(lg, rows: list[dict]) -> tuple[dict, dict, list]:
    """(games: game id -> {pid: status}, players: pid -> latest entry, unmatched rows)."""
    by_name = {fold(t["full_name"]): tid for tid, t in lg.teams.items()}
    games_by_key = {}
    for g in lg.all_games.itertuples():
        games_by_key[(g.us_date.strftime("%m/%d/%Y"), f"{g.awayTeam_teamTricode}@{g.homeTeam_teamTricode}")] = g.gameId

    def player_id(name: str, tid: int | None):
        last, _, first = name.partition(",")
        wanted = fold(f"{first} {last}")
        flipped = fold(f"{last} {first}")   # names written family name first, e.g. Yang Hansen
        bare = re.sub(r" (jr|sr|ii|iii|iv)$", "", wanted)
        pools = [lg.roster(tid)] if tid else []
        pools.append(list(lg.players.values()))
        for pool in pools:
            for pl in pool:
                f = fold(pl.name)
                if f in (wanted, flipped) or re.sub(r" (jr|sr|ii|iii|iv)$", "", f) == bare:
                    return pl.id
        return None

    games, players, unmatched = {}, {}, []
    for r in rows:
        tid = by_name.get(fold(r["team"] or ""))
        gid = games_by_key.get((r["date"], r["matchup"]))
        pid = player_id(r["player"], tid)
        if pid is None or tid is None:
            unmatched.append(r)
            continue
        entry = {"status": r["status"], "reason": r["reason"], "team": tid, "game_id": gid, "date": r["date"]}
        if gid:
            games.setdefault(gid, {})[str(pid)] = r["status"]
        players[str(pid)] = entry
    return games, players, unmatched


def _counts(entry: dict) -> bool:
    """Ignore G League assignments and two-way players (not in the rotation)."""
    return not entry.get("reason", "").startswith("G League")


# --- Checking for a new report -----------------------------------------------------------

def _apply(data: dict, lg, url: str, pdf: bytes) -> None:
    """Merge one report into data (see the module docstring)."""
    games, latest, unmatched = _match(lg, parse(pdf))
    reported_teams = {e["team"] for e in latest.values()}
    players = {pid: e for pid, e in data.get("players", {}).items() if e["team"] not in reported_teams}
    players.update(latest)
    data.update({
        "url": url, "published": report_time(url).isoformat(),
        "games": {**data.get("games", {}), **games}, "players": players,
        "unmatched": [f"{r['player']} ({r['team']})" for r in unmatched],
    })


def check(lg, force: bool = False) -> bool:
    """Read any reports we haven't read (looking at most every CHECK_MINUTES unless forced).
    Returns True when injuries.json changed."""
    if not _lock.acquire(blocking=False):
        return False
    try:
        data = load()
        if not force and time.time() - data.get("checked", 0) < CHECK_MINUTES * 60:
            return False
        _status["checking"] = True
        _status["error"] = None
        since = datetime.fromisoformat(data["published"]) if data.get("published") else None
        todo = _to_read(report_urls(), since)
        for url in todo:
            pdf = requests.get(url, headers=HEADERS, timeout=30)
            pdf.raise_for_status()
            _apply(data, lg, url, pdf.content)
        data["checked"] = time.time()
        _save(data)
        return bool(todo)
    except Exception as e:
        _status["error"] = str(e)
        traceback.print_exc()
        return False
    finally:
        _status["checking"] = False
        _lock.release()


def check_in_background(lg, force: bool = False, then=None) -> None:
    def run():
        if check(lg, force) and then:
            then()
    threading.Thread(target=run, daemon=True).start()


def status() -> dict:
    data = load()
    published = datetime.fromisoformat(data["published"]) if data.get("published") else None
    return {
        "checking": _status["checking"], "error": _status["error"],
        "published": published.astimezone(config.TZ) if published else None,
        "published_et": published.astimezone(ET) if published else None,
        "checked": datetime.fromtimestamp(data["checked"], config.TZ) if data.get("checked") else None,
        "unmatched": data.get("unmatched", []),
    }


# --- What predictions use --------------------------------------------------------------

def outs(data: dict | None = None) -> tuple[dict[str, set[int]], set[int]]:
    """(per-game outs for games in a report, players carried forward as out for later games)."""
    data = load() if data is None else data
    players = data.get("players", {})
    per_game = {gid: {int(pid) for pid, s in statuses.items() if s in OUT_STATUSES and _counts(players.get(pid, {}))}
                for gid, statuses in data.get("games", {}).items()}
    carried = {int(pid) for pid, e in players.items() if e["status"] == "Out" and _counts(e)}
    return per_game, carried


def player_notes(data: dict | None = None) -> dict[int, dict]:
    """Each listed player's latest status and reason, for showing beside his name."""
    data = load() if data is None else data
    return {int(pid): e for pid, e in data.get("players", {}).items() if _counts(e)}
