# NBA

Expected results for any NBA game, with the option to mark players unavailable, plus team
schedules and player profiles. Data comes from stats.nba.com through the
[nba_api](https://github.com/swar/nba_api) package. It runs only on your machine, at http://127.0.0.1:8001.

## Setup

Run `./run.sh`. The first run creates `.venv` and installs the dependencies. Then open http://127.0.0.1:8001.
The first page load downloads about 70 files from stats.nba.com (one to two minutes) and shows its progress.

## How data is fetched

- Every response is saved as JSON in `data/cache/`, so each request is only made once.
- **Last season** is downloaded once and kept.
- **This season** (schedule, results, rosters, on/off splits) is re-downloaded in the background
  when it's more than 6 hours old (`REFRESH_HOURS` in `app/config.py`). Pages show the cached data meanwhile
  and reload when the update finishes.
- **Refresh data** forces an update now. `python -m app.sync` (with `.venv` active) does the same from the terminal.
- Player bios and career stats are fetched when you open a player's page (kept 7 days and 1 day).
- stats.nba.com throttles quick bursts, so requests are spaced 0.7 seconds apart and retried.

## Pages

- **Teams:** every team by conference, ordered by projected net rating, plus a picker for any matchup.
- **Team:** projected ratings, the schedule (NZ time) with a win chance and expected score for each game,
  results, and the roster. **Mark out** takes a player out of every prediction until you mark him available again.
- **Game:** expected score and win chance, how the margin is built, a team comparison, and an expected box score
  for both teams. Tick **Out** next to any player to see the prediction without him (this page only), then
  **Save as unavailable for all games** to keep it. Finished games also show the actual box score.
- **Player:** bio, a playstyle summary, shot locations, estimated impact, the team's record with and without him,
  teams played for, career stats, playoffs and the last 10 games.

## How predictions work

All in `app/model.py`:

1. **Team ratings:** points scored and allowed per 100 possessions, and pace, from every game. Last season's
   ratings keep 75% of their distance from league average. This season's take over as games are played
   (half the weight after 15 games).
2. **Player impact:** how much better the team's offence and defence are with the player on court than off it,
   shrunk toward zero for small samples. The scale was checked against last season: for 117 players who missed
   8+ games, the real gap between with and without matched the estimates closely (slope 1.17, correlation 0.52).
3. **Minutes:** the 10 players with the most usual minutes play. If they add up to more than 240, the end of the
   bench loses minutes first. Players marked out free up minutes for the rest.
4. **Lineups:** a team's rating moves by each player's impact × the change in his share of court time.
   Roster and minutes changes since the rated season count at 35% (a full-strength roster is optimistic).
   Players marked out count in full.
5. **Score:** pace × each offence against the other defence, plus home court (+1.7, last season's average)
   and −1.5 points for the second night of a back-to-back. Win chance assumes real margins vary ±13 points
   around the prediction.
6. **Player lines:** expected minutes × each player's per-minute rates (last season at 60% weight).
   Points, assists and threes are scaled so they add up to the team's expected score.

## Limits

- There's no injury feed in the NBA's stats API, so nobody is marked out unless you do it.
- Rookies and players with no recent NBA minutes get a small role and typical bench rates until they play.
- Before the season starts, everything rests on last season plus roster moves; early-season numbers move a lot.
- The playstyle summary is generated from stats (usage, assist rate, shot zones, rebounding, blocks, steals),
  not written by a person.

## Code layout

| File | What it does |
|---|---|
| `app/nba.py` | stats.nba.com requests, the on-disk cache and rate limiting |
| `app/sync.py` | Decides what to download and runs it in a background thread |
| `app/model.py` | Team ratings, player impact, minutes and predictions |
| `app/profile.py` | Player profile: career, shot zones, playstyle |
| `app/main.py` | FastAPI routes and the saved list of unavailable players (`data/unavailable.json`) |
| `app/templates/` | One template per page, sharing `base.html` |
| `app/static/app.js` | Tabs, the Out checkboxes and the career chart |
