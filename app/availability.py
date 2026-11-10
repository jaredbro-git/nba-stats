"""Who's out. Two saved lists:

- Your list for every game (unavailable.json): a player on it misses every prediction until removed.
- Per-game lists (game_outs.json, game id -> player ids): set on a game's page. A game with its own list uses
  it instead of the all-games list for that game's two rosters (so a player can be out for one game only, or
  back for one game while still on the all-games list).

Plus the NBA's injury report (injuries.py), read automatically: for a game without its own list, players the
report has out for that game (or, for later games, players whose latest status is Out) are added to the
all-games list.

Every real prediction (pages, the tracker, the simulator, the phone bundle) goes through out_for_game.
"""

import json

from . import config, injuries


def _read(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


def _write(path, value) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value))
    tmp.replace(path)


def game_outs_file():
    return config.DATA_DIR / "game_outs.json"


def saved_out() -> set[int]:
    """The all-games list."""
    return set(_read(config.UNAVAILABLE_FILE, []))


def save_out(ids: set[int]) -> None:
    _write(config.UNAVAILABLE_FILE, sorted(ids))


def game_outs() -> dict[str, set[int]]:
    """Per-game lists: game id -> players out for that game."""
    return {gid: set(ids) for gid, ids in _read(game_outs_file(), {}).items()}


def set_game_out(game_id: str, ids: set[int] | None) -> None:
    """Save a game's own list, or remove it (None) so the game goes back to the all-games list."""
    data = _read(game_outs_file(), {})
    if ids is None:
        data.pop(game_id, None)
    else:
        data[game_id] = sorted(ids)
    _write(game_outs_file(), data)


def rosters(lg, *team_ids) -> set[int]:
    return {p.id for p in lg.players.values() if p.team_id in team_ids}


def report_out(game_id: str | None, auto=None) -> set[int]:
    """Players the injury report has out for this game: its own entries if the game is in a report, else
    everyone whose latest status is Out. `auto` is injuries.outs(), passed when calling for many games."""
    per_game, carried = injuries.outs() if auto is None else auto
    return per_game[game_id] if game_id in per_game else carried


def out_for_game(lg, game_id: str | None, home: int, away: int, outs: dict | None = None, saved: set | None = None,
                 auto=None) -> set[int]:
    """Who's out for one game: its own list if it has one, else the all-games list plus the injury report
    (limited to its rosters). Pass `outs`/`saved`/`auto` when calling for many games, to read the files once."""
    outs = game_outs() if outs is None else outs
    chosen = outs.get(game_id) if game_id else None
    if chosen is None:
        chosen = (saved_out() if saved is None else saved) | report_out(game_id, auto)
    return chosen & rosters(lg, home, away)


def now_out(saved: set | None = None, auto=None) -> set[int]:
    """Who's out right now, for team ratings that aren't about one game: the all-games list plus everyone the
    injury report last listed as Out."""
    _, carried = injuries.outs() if auto is None else auto
    return (saved_out() if saved is None else saved) | carried
