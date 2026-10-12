# NBA

Expected results for any NBA game, with the option to mark players unavailable, plus team
schedules and player profiles. Data comes from stats.nba.com through the
[nba_api](https://github.com/swar/nba_api) package. It runs only on your machine, at http://127.0.0.1:8001.

## Setup

Run `./run.sh`. The first run creates `.venv` and installs the dependencies. Then open http://127.0.0.1:8001.
The first page load downloads about 70 files from stats.nba.com (one to two minutes) and shows its progress.

## Mac app

`./build-app.sh install` builds `NBA Stats.app` (Apple Silicon) and replaces the copy in
`/Applications`, then opens it. `./build-app.sh` on its own only builds `dist/NBA Stats.app`.

- The app runs the same web app in a native window (pywebview, packaged with PyInstaller).
  Closing the window quits it.
- Its data lives in `~/Library/Application Support/NBA Stats` (cache and saved unavailable players),
  separate from this folder's `data/`, so rebuilding keeps it. Logs: `~/Library/Logs/NBA Stats.log`.
- The app and `./run.sh` both use port 8001, so only one can run at a time.
- To ship a change: edit the code, then run `./build-app.sh install`.

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

- **Teams:** every team by conference, ordered by projected net rating, a picker for any team matchup, and a
  **Player matchup** search for any shooter and defender.
- **Team:** projected ratings, the schedule (NZ time) with a win chance and expected score for each game,
  results, the roster, and **shot charts** for the team's offence and for opponents' shots against it (defence).
  **Mark out** takes a player out of every prediction until you mark him available again.
- **Game:** expected score and win chance, how the margin is built, a team comparison, and an expected box score
  for both teams. Tick **Out** next to any player to see the prediction without him (this page only), then
  **Save as unavailable for all games** to keep it. **Matchups** lists each side's top 5 scorers with their likely
  defender; pick a different defender to see how the prediction changes. Finished games also show the actual box score.
- **Player:** bio, a playstyle summary, a **shot chart** (any season of his career since 1996-97, or his whole
  career combined), **matchups** (who guarded him and how he scored; who he guarded and how they scored), estimated
  impact, the team's record with and without him, teams played for, career stats, playoffs and the last 10 games.
  **Against** picks one opponent for both the shot chart and the matchups; the matchups then list that team's whole
  roster, including players he's never faced. Click any matchup for its **expected outcome** in a popup.
  Each matchups tab has a search box (**Find a defender** / **Find a shooter**) for any player, retired ones included.
  The tables sort by any column or by presets (best/worst defenders first, which uses the sample-adjusted
  **Est. effect**), and filter by minimum possessions, position and name. Without a team picked, head-to-heads
  under 5 possessions aren't listed.

- **Predictions:** the prediction tracker. Each game's prediction is saved while the app is open (games starting
  within 48 hours, refreshed until tip-off) and scored when the game is final: winners picked, margin and total
  misses, Brier score and calibration. Regular season, playoffs and preseason are scored separately. Games the app
  wasn't open for beforehand aren't tracked. Preseason games played before the tracker existed are "backfilled"
  (predicted afterwards, fair only because no regular-season games had been added to the model's data since) and
  can be left out. Saved in `predictions.json` in the data folder (`app/tracker.py`).
- **Season sim:** the rest of the season, play-in and playoffs simulated 10,000 times (`app/simulator.py`):
  projected records, 80% win ranges, #1 seed, top 6, play-in, playoffs, each round and title odds. "What if" a
  player misses the next N games or the rest of the season; players on the unavailable list miss their next 10 by
  default. Each simulated season also draws every team's true strength from a spread around its projection (±3.5
  points before the season, narrowing to ±1.5 as games are played). Games not scheduled yet (NBA Cup knockouts and
  the games added later for teams knocked out of the Cup) are played against a league-average opponent.
- **Trade machine:** move players between two teams and compare ratings, rotation minutes, projected records and
  playoff and title odds before and after. Traded players count in full against each team's pre-trade rotation,
  like marking a player out. No salary-cap check (the stats API has no contract data).

### Shot charts
Every shot's court location comes from the NBA's shot chart data (back to 1996-97), downloaded the first time a chart
is opened: one request per player-season or team-season (offence, or every shot against the team), each with that
season's league FG% for every zone. Finished seasons are kept; the current season is refreshed like the rest of its
data. A career chart downloads one season at a time in the background (about 30 seconds for a 20-season career).
Shots are stored compactly (zone codes, only the columns the charts use). Hexagons are 1.5 ft across: size shows how often shots come from there, and colour
compares FG% with the league's FG% in the same court zone (blue colder, red hotter), with small samples pulled toward
league average. Defence charts colour opponents' shooting, so red is where a team gives up good shots.

### Matchups
All in `app/matchups.py`, from the NBA's matchup tracking (every shooter–defender pair, whole seasons from
2017-18; each older season counts 60% as much as the one after it):
- **Defender rating:** points per possession allowed compared with what those shooters usually score. It's 70%
  closest-defender FG% (vs the shooters' usual FG%) and 30% matchup points compared with players at the same
  position, because matchup points unfairly charge help defenders (a big who leaves his man to protect the rim).
- **Pair effect:** a shooter's record against a defender, shrunk toward that defender's rating.
- **Height:** fitted from every pair with known heights. Once the defender's own ability is counted, height barely
  moves FG% (about 0.01 points per inch), so it's a small term. (Fitted on points instead, taller defenders looked
  worse, because matchup points charge bigs for switches and for the men they leave.)
- **Expected outcome popup:** points per 100 possessions, FG%, 3P% and shot volume for any shooter–defender pair,
  plus a per-game version (a primary defender guards about 40% of his possessions). Pairs that have never met are
  estimated from the defender's ratings (including FG% and 3P% allowed as the closest defender) and height.
- **In predictions:** a primary defender guards about 40% of a scorer's possessions, and 60% of a scorer's change
  reaches the team score. The likely matchups (whoever has guarded each scorer most) are already part of the team
  ratings, so only the defenders you change move the prediction.
- The NBA doesn't record which defender was on each shot, so matchups have no court locations.

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
| `app/shots.py` | Shot charts: hexagon bins, zones, the court drawing |
| `app/matchups.py` | Defender ratings, pair effects and matchup changes to predictions |
| `app/templates/_shotchart.html` | The shot chart, shared by the player and team pages |
| `app/main.py` | FastAPI routes and the saved list of unavailable players (`data/unavailable.json`) |
| `app/templates/` | One template per page, sharing `base.html` |
| `app/static/app.js` | Tabs, the Out checkboxes and the career chart |
| `desktop.py` | Mac app launcher: starts the server and opens the window |
| `build-app.sh`, `build_tools/` | Builds and installs the Mac app; draws its icon |
