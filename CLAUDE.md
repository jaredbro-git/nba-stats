# NBA Stats: handoff for new sessions

A personal NBA app for one user in New Zealand (times shown in Pacific/Auckland). FastAPI + Jinja2 +
pandas, data from stats.nba.com through `nba_api`, no database (a JSON file cache). It runs as a Mac app
(`/Applications/NBA Stats.app`, Apple Silicon only, this Mac only) and as a dev server. `README.md` is the
user-facing description of every page and of the model; this file is the working knowledge behind it.

## Run, build, ship

- **Mac app:** `./build-app.sh install` builds `dist/NBA Stats.app` (PyInstaller + pywebview, ad hoc signed,
  bundle id `nz.jaredbro.nbastats`), quits the running app, replaces `/Applications/NBA Stats.app` and reopens it.
  **Every change ships this way**, then check pages with `curl http://127.0.0.1:8001/...`.
  - Data: `~/Library/Application Support/NBA Stats/` (`cache/`, `unavailable.json`, `predictions.json`).
    `desktop.py` sets `DATA_DIR` there. Log: `~/Library/Logs/NBA Stats.log`.
  - Data added in new code is fetched by the app's own background sync. To skip waiting, copy new cache files
    from the project's `data/cache/` into the app's `cache/` (never overwrite existing ones).
- **Dev server:** `./run.sh` uses port **8001**, the same port as the installed app, so only one can run. While
  the app is open, test on a spare port instead: `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8011`
  (uses the project's `data/`). Kill it afterwards.
- Python 3.14 (Homebrew). Two virtualenvs: `.venv` (run.sh) and `.venv-build` (build-app.sh, `requirements-app.txt`).
- `python -m app.sync` forces a full refresh from the terminal.

## Code layout

| File | What it does |
|---|---|
| `app/config.py` | Paths (`DATA_DIR` from env), timezone, `PORT = 8001`, `REFRESH_HOURS = 6`, season labels |
| `app/nba.py` | stats.nba.com client: every response cached as JSON (`fetch(key, request, max_age)`), 0.7 s between requests, retries, falls back to stale cache. All endpoint wrappers live here |
| `app/sync.py` | Background refresh thread: last season once, current season every 6 h, and as soon as a regular-season game should be over (`results_due()`: tip-off + 3 h, not yet in the game logs; retried every 30 min, gives up after 2 days). `needs_refresh()` also triggers when newly added data types are missing |
| `app/model.py` | `League`: team ratings, player rates/impact, rotations, `predict()`, `quick_margin()`, `net_rating()`, `with_trade()`. `model.league()` rebuilds when any cache file changes |
| `app/matchups.py` | Shooter–defender matchups 2017-18→now: defender ratings, pair effects, height effect, `estimate()` for any pair, matchup changes to predictions |
| `app/shots.py` | Shot charts: on-demand downloads, hexagon bins, zones, court SVG, background career downloads |
| `app/profile.py` | Player card data: bio/career (on-demand API calls), playstyle traits, `season_table()`, `similar()` ("plays like") |
| `app/simulator.py` | Season simulator (numpy, 10,000 seasons, play-in + playoffs) |
| `app/tracker.py` | Prediction tracker (`predictions.json`) |
| `app/injuries.py` | The NBA's official injury report PDF (official.nba.com, read with pypdf by word positions): `check()` every 15 min from `main._background()` and the **Check now** button (POST `/injuries/check`) on Today, team and game pages. `injuries.json`: per-game statuses + each player's latest status. Out/Doubtful count for a game in a report; for later games, latest status Out carries forward until the team's next report clears it. G League/two-way rows ignored. The index page lists only today's reports; older ones stay at `Injury-Report_<day>_<time>.pdf`, so the first run (and after sleep) reads each missed day's last report (past week) |
| `app/availability.py` | Who's out: the all-games list (`unavailable.json`) and per-game lists (`game_outs.json`, set on a game page) that replace it for that game. **Every real prediction goes through `out_for_game`** (pages, tracker, simulator `game_outs=`, phone bundle meta `game_outs`). A game without its own list = all-games list ∪ injury report (`report_out`); team ratings not tied to a game use `now_out` (all-games ∪ carried-forward Outs). "Save for all games" never copies report players onto your list (form field `auto`) |
| `app/main.py` | All routes, `_page()` wrapper (starts sync, shows loading page on first run, runs the tracker), nav list, Jinja filters/globals, unavailable-player list |
| `app/templates/` | One template per page on `base.html` (nav). Shared: `_shotchart.html` (macro), `_playersearch.html` (macro), `_matchup_detail.html` (popup body) |
| `app/static/app.js` | All JS: tabs, clickable rows, Out toggles, matchup selects, popup dialog, player search, generic sortable tables, charts (Chart.js 4.4.1 from cdnjs) |
| `desktop.py`, `build-app.sh`, `build_tools/make_icon.py` | Mac app launcher, build/install script, icon drawing |

## Pages (nav order) and routes

- **Teams** `/` (home): teams by conference + team matchup picker + player matchup search. Also owns
  `/team/<ABBR>?season=` (schedule with predictions, roster with Mark out, offence/defence shot charts back to
  1996-97), `/game/<id>?out=&mu=` and `/matchup?home=&away=&out=&mu=` (prediction, margin factors, expected box
  scores with Out checkboxes, editable Matchups card, actual box score when final).
- **Today** `/today?date=YYYY-MM-DD` (NZ day): game cards with live scores (`nba.scoreboard()`, ScoreboardV3, kept **in memory** for 45 s:
  writing to the cache folder would rebuild the model and re-copy the phone), the saved pre-game prediction once a game starts
  ("not tracked" otherwise), right/wrong, who's out. Refreshes every minute while a game is on (not while a popup is open).
  Cards open the game in a popup (`initGamePopups`: `<dialog>` with the game page in an iframe; inside an iframe base.html adds
  `html.embedded`, which hides the header/nav, keeps /game/ links in the popup and sends other links to the main window;
  the page reloads on close if anything changed in the popup). cdn.nba.com live JSON returns 403 here.
- **Players** `/players` (sortable/filterable table of rostered players, find a player, compare picker),
  `/players/compare?a=&b=`, `/players/<id>?season=&vs=` (the player card: shot chart with season/Career and
  "Against" team filter, Matchups card with Guarded by / Guarding tabs, search, sort and filters, Plays like,
  impact, career). `/player/<id>` 301-redirects to `/players/<id>`. **All player links must use `/players/<id>`.**
- **Predictions** `/predictions?kind=reg|pre|post&backfilled=0|1`. Upcoming and Results tables use the generic sortable-table code with one shared "Find games" bar
  (team text search, date, favourite's chance; `data-for="upcoming-table results-table"`) plus a Right/Wrong filter and sort on
  Results. The phone Tracker has the same filters.
- **Season sim** `/simulator?miss=<pid>:<games|rest>,...&saved=0|5|10|20|rest`.
- **Trade machine** `/trades?a=<ABBR>&b=<ABBR>&send=<pid>&send=<pid>` (one `send` per ticked player, comma lists also accepted).
- Fragments/JSON: `/matchup-detail?shooter=&defender=` (popup HTML), `/player-search?q=` (JSON, accent-insensitive,
  uses nba_api's static list of every player). POST `/unavailable`, `/unavailable/save`, `/refresh`.
- Nav entries live in `templates.env.globals["nav"]` in `main.py` as `(href, label, other path prefixes)`; add a
  page there only when it exists (no dead links).

## Data: what the API gives, verified

- Seasons: current = the season starting in October of this year from August on (`config.current_season()`).
  The 2026-27 regular season starts 20 Oct 2026 (US). Until then, "this season" data is mostly empty and the
  model runs on 2025-26.
- Game id prefixes: `001` preseason, `002` regular season, `004` playoffs, `005` play-in, `006` NBA Cup final.
  NBA Cup knockout games appear with team id `0` until decided; about 2 games per team are added later.
- **Shots** (`ShotChartDetail`): back to **1996-97**. A league-wide request is **capped at 102,400 rows** (a season
  has ~220k). One player-season or one team-season is one request (~1–4 s) and includes that season's league FG%
  by zone. Defence = `team_id=0, opponent_team_id=X`. A whole career can't be fetched in one request (empty
  result), so careers download season by season in a background thread. Stored compactly (zone codes) as
  `pshots_<pid>_<season>`, `tshots_<tid>_<season>`, `dshots_<tid>_<season>`. Old abbreviations (SEA, NJN, CHH,
  NOH…) map to current franchises in `shots.OLD_ABBR`.
- **Matchups** (`LeagueSeasonMatchups`): one request per season, ~130–150k pairs, whole seasons from **2017-18**
  (2016-17 is partial, ~3.5k pairs, not used). `matchups_<season>`, all seasons downloaded by sync.
- **Closest-defender FG%** (`LeagueDashPtDefend`, Overall and "3 Pointers"): from 2013-14. Used for the
  current and previous season (`defend_`, `defend3_`).
- No injury, contract or salary data anywhere in the stats API (injuries come from the official injury report PDFs, see injuries.py).
- stats.nba.com throttles bursts and usually blocks cloud IPs (so GitHub Actions can't refresh data).
- cdn.nba.com logos/headshots fail in headless Chrome (HTTP2 errors): expected in screenshots, fine in the app.

## Model decisions (and why)

Game predictions (`model.py`): team ratings per 100 possessions (last season regressed 25% to average, blended
with this season: half weight after 15 games) + player impact (shrunk on/off splits) × change in share of court
time. Score = pace × each offence vs the other defence + home court (league average, ~1.7) − 1.5 for a
back-to-back. Win chance = normal CDF of margin / 13.
- Player impact (2026-10-29, `tools/fit_impacts.py`, out of sample on 2023-24→2025-26, 13% less error than the old rule):
  on/off splits from this season and the three before (×0.6 per season back), evidence = decayed harmonic on/off
  minutes, own split gets half weight at `IMPACT_HALF_TRUST = 1400`; with little evidence a player sits at
  `IMPACT_PRIORS` for his group (rookie / 2nd / 3rd season from the roster's EXP; fringe veteran = under 600 on-court
  minutes last season; else regular veteran). Rookies −1.8 and fringe veterans −1.7 net per 100 (both weak on offence).
  `IMPACT_SCALE = 2.1` (`tools/fit_impact_scale.py`: keeps real with/without splits moving the same multiple of the
  estimate as the old 1.4 did; correlation 0.39 vs 0.37). Team net spread SD 5.4 (old 5.9, real ~6.0).
  Minutes when players are out were checked against 2,158 team-games in 2025-26 with a regular missing: the existing
  rule (top 10 scaled to 240) is about right on average, so it was kept; minutes-per-team-game was worse.
- `ROSTER_WEIGHT = 0.35`: offseason roster/minutes changes are damped and centred on the league average,
  because a full-strength rotation is optimistic and part of each player's value is already in the team rating.
  Projected net-rating spread SD ≈ 5.6 vs last season's actual 6.0.
- Absences (2026-11-06, `tools/fit_absences.py`): every 2025-26 game predicted from data before it (rating to date,
  impacts from earlier seasons, who actually sat). The old rule (out players in full, this season's absences credited back
  at ROSTER_WEIGHT 0.35) scored Brier 0.2138, worse than ignoring absences (0.2054): absences were counted about twice.
  Now `ABSENCE_WEIGHT = 0.5` (players marked out / on the injury report, and traded players, measured against the
  pre-trade/healthy rotation) and `CUR_ROSTER_WEIGHT = 0.8` for this season's part of the roster adjustment
  (`_full_strength` stores adj_off/adj_def already weighted; the bundle sends roster_weight 1 and absence_weight) → 0.2007.
  Best was 0.40/0.65 (halves: 0.25/0.55 and 0.50/0.75); 0.5/0.8 chosen because older impacts make the backtest's
  weights a little low. Trading a player away for nothing = marking him out (still equal).
- Rotation: top 10 by usual minutes; if their minutes exceed 240 the end of the bench is squeezed (stars keep
  their minutes); if under 240 (absences) everyone scales up, capped at 40.
- Player lines: minutes × per-minute rates; points/assists/threes scaled to the team score, the rest to pace.

Matchups (`matchups.py`):
- Matchup points unfairly charge help defenders (a big who leaves his man to protect the rim is charged when
  that man scores), which made rim protectors look like the worst defenders. Fixes: defender rating = 70%
  closest-defender FG% allowed (converted to points) + 30% matchup points **compared within position group**.
  Result looks right (Holmgren, Wembanyama, Adebayo, Amen Thompson, Gobert rate well).
- Height effect fitted from all pairs: fitted on points it said taller defenders give up more (same bias), so
  it's fitted on FG% beyond the defender's closest-defender FG% and converted to points. Result ≈ 0.013 FG% points
  per inch, i.e. height barely matters once defender quality is known. The popup says so.
- Seasons decay ×0.6 per year. Defaults on the game page (likely defender = most possessions guarded) add
  nothing to predictions (already in team ratings); only user changes move them: primary defender guards ~40%
  of possessions, 60% of the scorer's change reaches the team score. Effects are small by design (±~1 pt).
- No per-shot defender exists in public data, so matchups have no court locations. A possible estimate
  (weight each game's shots by that game's matchup shares from `BoxScoreMatchupsV3`) was discussed, not built.

Simulator: team-strength uncertainty 3.5 points before the season narrowing to 1.5 as this season's games gain
weight (2.5 gave OKC 43% title odds, which was overconfident; now ~38%). Unscheduled games are played against a
league-average opponent so every team plays 82. Series odds are computed game by game (checked: p=0.6 →
0.7102). Saved unavailable players miss their next 10 games by default.

Tracker: predictions logged for games starting within 7 days while the app is open, redone on every update
until tip-off (so each new result re-predicts that team's next games), then frozen. `main._background()` runs
sync + tracker every 10 min (1 min while a refresh runs) even if no page is opened (`NBA_STATS_NO_BACKGROUND=1`
turns it off for test servers). Wording lives in `tracker.HOW_TRACKED` (also sent to the phone in bundle meta). Never predicted after the fact, except the preseason games already played when it was added
("backfilled", allowed only while no regular-season games are in the model's data). Preseason scored separately
(first 36 backfilled: 47% winners, 90%+ favourites 0/5, because stars rest).

## UI conventions

- **Liquid Glass** (end of `style.css`): translucent panels (`--glass`, `--glass-strong`, `--chip` for glass-in-glass) with
  `backdrop-filter` blur + saturate, a bright top edge (`inset 0 1px 0 var(--glass-edge)`) and a soft shadow, over a fixed colour
  backdrop (`--backdrop`). Nav is a sticky glass pill. Solid fallback under `prefers-reduced-transparency`. Inner surfaces use
  `--chip`, never `--page` (that punches a solid hole in the glass).
- **Out checkboxes** (`.out-toggle`) never reload on tick: `initOutDock(shown, saved, preview)` shows a docked glass bar
  (`#out-dock`) whose buttons submit `#out-form` (`out` input follows the ticks): Update prediction (`?out=`), Save for this game
  (POST `/game-outs`, `clear=1` removes the game's list), Save for all games (POST `/unavailable/save`). Team roster uses it too.

- Same look as the user's other local apps: CSS tokens in `style.css` with dark mode via `prefers-color-scheme`,
  cards, tiles, tabs (`.tabs` + `data-tab` → `#tab-<name>`), `tr[data-href]` rows are clickable.
- Shot chart colours: diverging blue (colder) ↔ grey ↔ red (hotter), 4 steps each way via `color-mix` classes
  `c4…c1 mid h1…h4`; hexagon size = frequency; small samples shrunk (6 pseudo-shots).
- Generic sortable tables (a controls block can serve several tables: `data-for="a b"`; a table can have several blocks;
  text filters match every word): `table[data-sortable data-page data-sort data-tiebreak]`, rows carry values in
  lowercase `data-*` attributes (HTML lowercases attribute names), controls in `.mu-controls[data-for=<id>]` with
  `data-filter`, `data-filter-min`, `data-filter-text`, `data-hide-never`, `data-sort-preset`.
- Player search box: `player_search(label, placeholder, fixed_shooter=, fixed_defender=, slot=)`; `slot="go"`
  opens the card, other slots call `window.onSlotPicked(slot, player)` defined by the page.
- Matchup popup: any `[data-matchup-open="shooter:defender"]` or `tr[data-matchup]` opens `#matchup-dialog`
  (each page that uses it includes the `<dialog>`).
- Jinja filters: `signed` (sign decided after rounding, so no "−0"), `pct`. Globals: `logo`, `headshot`,
  `height`, `court_svg`, `nav`.
- Copy style: plain English, explain estimates honestly in the UI (each estimate has a "?" or footnote).

## How changes were verified

- Model changes: small scripts with `PYTHONPATH=. .venv/bin/python` printing real outputs (e.g. OKC vs MIN,
  SGA out, top defenders, simulator totals: title sums to 1, 16 playoff teams, 41 avg wins, 82 games each).
- Pages: curl every route for 200 and check `dev.log` for tracebacks, then **browser tests with puppeteer-core
  driving the installed Google Chrome** (scripts lived in the session scratchpad; recreate as needed: launch with
  `executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`). Use
  `page.setViewport({width: 390, isMobile: true})` for phone checks (headless windows can't go below ~500px), and
  check `document.documentElement.scrollWidth - innerWidth === 0`. Test forms by clicking like a user: a bug
  where multiple `send=` params collapsed to one was hidden by a hand-written URL.

## Git

- Public repo `github.com/jaredbro-git/nba-stats`, branch `main`. Commit identity is set in this repo
  (`jaredbro-git`, GitHub noreply email); end commit messages with the attribution line the session provides.
- **Commit and push only when the user asks.** Before committing, check `git status` (never commit `data/`,
  `build/`, `dist/`, `.venv*`) and scan the diff for personal details.
- Last commit: `737d2f1` (Mac app, shot charts, matchups, tracker, simulator, trade machine). **Uncommitted:**
  the Players section (`/players`, compare, player card moved to `/players/<id>`, Plays like, generic table
  sorter) and this file.

## Next up (agreed with the user, in this order)

1. **Play types** (Synergy, `SynergyPlayTypes`): points per possession by play type for offence and defence, with
   percentiles. Lives in **Players** (leaderboards + a section on the player card).
2. **Shot creation**: FG% by closest-defender distance, dribbles, catch-and-shoot vs pull-up, touch time, shot
   clock (`PlayerDashPtShots`, `LeagueDashPlayerPtShot`). Also in Players.
3. **Lineups**: best/worst 5-man and 2-man combinations by net rating (`TeamDashLineups`, `LeagueDashLineups`).
4. **League shot trends by era**: league zone averages per season 1996-97→now (one shot request per season returns
   them) as a shot-map/zone-share timeline.
5. **Game flow** on finished game pages: win-probability line (`WinProbabilityPBP`) and that game's shot chart.

Each new feature gets its own page in the nav unless it belongs to an existing page (player analytics go under
Players; per-game things go on the game page). Rebuild and install the app after each.

## Known limitations

- The tracker only scores games the Mac or the iPhone app saw in the week before tip-off. The Mac sleeps while the user is at work
  (most tip-offs are NZ midday-afternoon): on 2026-11-09 only 30% of the Mac's picks had been updated within 30 min of tip-off
  (median 3 h before, 20% over a day). The iPhone app now saves its own picks too (see below).
- Rookies with no NBA minutes get a small default role and bench-average rates.
- First load of a heavy player page (e.g. LeBron: hundreds of matchup rows, ~1.2 MB) takes ~5 s after the app
  opens (matchup history loads, ~2 s), ~1 s after.
- Trade machine has no salary-cap check (no contract data).

## iPhone app (`ios/`, started 2026-10-29; the user's phone is now an iPhone 16)

Injury report reaches the phone in bundle meta `injuries` (`games`, `carried`, `notes`, `published`, and `state` = the
Mac's injuries.json games/players): `League.outFor` mirrors `out_for_game`, `AppModel.nowOut`/`simInputs` mirror
`now_out`/`main._sim_inputs`; `Simulator.run` takes `gameOuts:` explicitly (parity runs without it).

**The phone keeps up without the Mac** (added 2026-11-09; `AppModel.update()`, run every 5 min while open (1 min with a
live game), by background refresh, and after each copy):
- Scores for any game in the last 3 weeks the bundle hasn't got final (`finals.json`).
- Results: LeagueGameLog T/P for regular-season games missing from the bundle's logs → `phone-games.json` →
  `League.redoRatings` (`Ratings.swift`: port of `_team_seasons`, `_league_avgs`, `_home_advantage`, `_minute_shares`,
  `_build_players` minutes/rates, `_full_strength`, `league_avg`; needs bundle meta `rating_params` and team_games `min`).
- Injury report: `Injuries.swift` ports injuries.py. PDFKit's per-character positions are unreliable on these PDFs, so it
  reads each column as a strip (`page.selection(for: rect).selectionsByLine()`), giving pypdf's x positions. Starts from
  the Mac's `state` and merges newer reports; whichever read the newer report wins (`injuriesOnPhone`). Not used with
  bundles that lack `state`.
- Picks: `phone-picks.json`, saved like tracker.update. `AppModel.picks` merges with the Mac's, taking the one saved later;
  sent to the Mac on each copy (`POST /share/picks` → `tracker.merge_phone`, which keeps the later pick before tip-off and
  marks it `source: "iphone"`; the bundle's predictions table has `source`).
- Tip-off reminders (`Reminders.swift`): local notifications per start time (Every game / My teams, N min before);
  background refresh task `nz.jaredbro.nbastats.refresh` (Info.plist `BGTaskSchedulerPermittedIdentifiers`, `fetch`).
  Settings and status are on the Sync & updates sheet.
- Tests: `NBA_CACHE=<data>/cache ios/Tools/parity.sh b.db e.json` also redoes ratings from the bundle's logs (must equal
  team_strength etc.) and checks downloaded log rows against the bundle's; `ios/Tools/injuries-parity.sh b.db *.pdf`
  compares the PDF reader and name matching with injuries.py (21 reports identical on 2026-11-09, 11,328 parity checks).

Native SwiftUI for iOS 26+ (Liquid Glass tab bar, `.glassEffect` cards on Today/game header), built with xcodegen
(`ios/project.yml`). Same hybrid design as the Android app it replaces: the Mac's bundle over Wi-Fi (app/phone.py,
Bonjour `_nbastats._tcp`, pairing code on the Mac's Phone page), the model run on the phone, live data from stats.nba.com.
- Tabs: Today (game cards like the Mac's Today page), Teams (team page: ratings/ranks, upcoming with per-game outs,
  results, roster switches), Players (sort/filter/search) → player card (bio, tiles, playstyle, plays like, Canvas shot
  chart, matchups, career, estimate sheet), Tracker (filters as the Mac), What If (Season sim | Trade machine). Game page:
  prediction, factors, comparison, Who's out (switches update instantly; "Save for all games" saves to the phone's list),
  matchups with defender menus, live/final box.
- `NBAStats/Data`: Db (sqlite3, rows as dicts), League/Matchups/Simulator/Tracker/Shots (ports of the Kotlin, which
  match Python), Ratings/Injuries/OnPhone/Reminders (keeping up, above), Nba (stats.nba.com, cached in Caches/nba; live scores from ScoreboardV3), Store (`AppModel`: bundle,
  league, phone's out list in UserDefaults, live scores), MacLink (from Spotify Stats' iOS app). Swift's sort isn't
  stable: use `stableSorted` wherever order matters (rotations, lines).
- **Parity:** `python -m app.bundle /tmp/b.db /tmp/e.json` then `ios/Tools/parity.sh /tmp/b.db /tmp/e.json` (compiles the
  Data files for macOS). Passed 1,091 checks on 2026-10-29. Keep Python and Swift in step.
- Build/test: `cd ios && xcodegen generate && xcodebuild -scheme NBAStats -sdk iphonesimulator -derivedDataPath build
  CODE_SIGNING_ALLOWED=NO build`; Simulator with real data: install, then copy a bundle to the app container's
  `Library/Application Support/nba-bundle.db` (`xcrun simctl get_app_container <sim> nz.jaredbro.nbastats data`).
  Launch options for screenshots: `-startTab Players`, `-route game:<id>|team:<id>|player:<id>`.
- Install on the phone: `ios/install.sh` (team from the Apple Development certificate; builds for the
  connected iPhone by id, which also registers it with the team). First installed on the user's iPhone 16 on 2026-10-29
  (paired by cable, Developer Mode on). The macOS keychain lists 0 "valid identities" but signing works via Xcode.
- `ios/Tools/make_icon.py` draws the icon from build_tools/make_icon.py.

## Android app (`android/`, retired 2026-10-29: the user moved to an iPhone; kept for reference, not maintained)


Native Kotlin + Jetpack Compose for the user's Samsung Galaxy A55 (same setup as Spotify Stats' Android app).
Hybrid: the Mac does the heavy modelling and serves a **phone bundle**; the phone runs the prediction maths
itself and fetches live things (scores, box scores, shot charts, bios, careers) from stats.nba.com directly.

- Mac side (done, installed): `app/bundle.py` builds the bundle (SQLite: meta, teams, team_strength,
  team_seasons, players incl. playstyle/similar/defender numbers, games incl. preseason, player_games,
  team_games, matchup pairs involving rostered players, player_names; ~37 MB, 17 MB gzipped, ~5 s).
  `app/phone.py`: Bonjour `_nbastats._tcp`, share server on port **8014** (LAN), phone pairing with a 6-digit
  code shown on the Mac's **Phone** page (`/phone`), `/share/bundle` (paired token only; rebuilt when cache
  files or the unavailable list change). Mac app now signed with keychain identity **"NBA Stats Signing"**
  (`build_tools/make_signing_identity.sh`) and has NSLocalNetworkUsageDescription/NSBonjourServices.
  `NBA_STATS_NO_PHONE=1` disables the link for test servers. `zeroconf` added to requirements.
- Phone side: `data/League.kt` + `data/Matchups.kt` port model.py/matchups.py (rotation, strength, predict,
  player lines, matchups apply/estimate, withTrade). **ParityTest passes at 1e-6** against Python:
  `python -m app.bundle /tmp/b.db /tmp/e.json` then
  `NBA_BUNDLE=/tmp/b.db NBA_EXPECTED=/tmp/e.json ./gradlew testReleaseUnitTest`. Keep Python and Kotlin in step.
  `data/Store.kt` (bundle + Unavailable = Mac list ∪ phone adds − phone removes), `data/MacLink.kt` (find/pair/copy,
  auto-copy every 30 min while home), `data/Nba.kt` (stats.nba.com with nba_api's headers; cached in cacheDir),
  `data/Shots.kt` (hex bins). UI: `ui/App.kt` (bottom nav Teams/Players, LiveScores refresh every 1 min while a
  game is on), TeamsScreen (today's games + conferences; team page with schedule/results/roster Out switches),
  GameScreen (prediction, factors, comparison, expected box with Out checkboxes, matchups with defender picker,
  live/final box), PlayersScreen, PlayerScreen (bio/career via API, playstyle, plays like, Canvas shot chart,
  matchups with sorts), Estimate sheet, SyncScreen.
- Bundle **FORMAT** (bundle.py, League.FORMAT, currently 3): bump both together whenever tables change; the phone
  shows "older format" on the sync screen (no crash) and the Mac rebuilds since FORMAT is in phone._signature. Format 3
  added the `predictions` table (the Mac's tracker records; the signature also watches predictions.json).
- Phone pages (bottom bar): Teams, Players, Tracker (Mac's saved predictions scored on the phone, `data/Tracker.kt`),
  Season (`data/Simulator.kt`, port of simulator.py, 10k sims split over cores, ~1 s on the A55; what-ifs + saved-list
  choice), Trades (withTrade + two sims, ratings/rotation before/after). All checked on the A55 on 2026-10-17 against the
  Mac: tracker tiles identical, sim title odds within noise, LAL→OKC Reaves trade ratings identical.
- ParityTest also covers the simulator (within Monte Carlo tolerance), seriesWin and quickMargin.
- Build: `export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
  ANDROID_HOME=/opt/homebrew/share/android-commandlinetools; cd android && ./gradlew assembleRelease`
  (release signed with the debug key). Install: `adb -s adb-R5CX71DNRFV-yZvQrj._adb-tls-connect._tcp install -r
  app/build/outputs/apk/release/app-release.apk` (the A55 was connected over Wireless debugging on 2026-10-16).
  Emulator testing: `assembleDebug`, install, `adb push bundle.db /data/local/tmp/` then
  `run-as nz.jaredbro.nbastats cp /data/local/tmp/nba-bundle.db databases/` (emulator can't Bonjour the Mac).
- Next: check stats.nba.com over mobile data; whatever the user asks for next.
- Everything above (Players section, CLAUDE.md, bundle/phone/Android) is **uncommitted**.
