package nz.jaredbro.nbastats.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import nz.jaredbro.nbastats.data.Game
import nz.jaredbro.nbastats.data.League
import nz.jaredbro.nbastats.data.Player
import nz.jaredbro.nbastats.data.Store
import nz.jaredbro.nbastats.data.Team
import nz.jaredbro.nbastats.data.Unavailable
import java.time.LocalDate

private data class TeamRow(val team: Team, val net: Double, val record: String, val next: String?)
private data class GameRow(val game: Game, val homeWin: Double, val homePts: Double, val awayPts: Double)
private data class HomeData(val day: LocalDate?, val games: List<GameRow>, val conferences: Map<String, List<TeamRow>>)

fun recordText(lg: League, teamId: Long): String {
    val cur = lg.seasons[lg.cur]?.get(teamId)
    if (cur != null && cur.gp > 0) return "${cur.w}–${cur.l}"
    val prev = lg.seasons[lg.prev]?.get(teamId) ?: return ""
    return "${prev.w}–${prev.l} last season"
}

/** Home: today's games (NZ time) with scores and predictions, then every team by projected strength. */
@Composable
fun TeamsScreen(nav: NavController) {
    val lg = rememberLeague() ?: return Loading("Opening the data from your Mac…")
    val context = LocalContext.current
    val changes = Unavailable.changes
    val data by produceState<HomeData?>(null, lg, changes) {
        value = withContext(Dispatchers.Default) {
            val out = Unavailable.effective(context, lg)
            val today = LocalDate.now(Store.TZ)
            // Today's games, or the next day that has some.
            val upcoming = lg.games.filter { it.start != null && it.homeId in lg.teams && it.awayId in lg.teams }
            val day = upcoming.map { it.start!!.atZone(Store.TZ).toLocalDate() }.filter { !it.isBefore(today) }.minOrNull()
            val games = upcoming.filter { it.start!!.atZone(Store.TZ).toLocalDate() == day }.map { g ->
                val p = lg.predict(g.homeId, g.awayId, lg.outFor(g.id, out), g.usDate, g.neutral)
                GameRow(g, p.homeWin, p.home.pts, p.away.pts)
            }
            val rows = lg.teams.values.map { t ->
                val next = lg.schedule.firstOrNull { (it.homeId == t.id || it.awayId == t.id) && it.status != 3 }
                val nextText = next?.let { g ->
                    val home = g.homeId == t.id
                    "Next: ${if (home) "vs" else "@"} ${lg.teams[if (home) g.awayId else g.homeId]?.abbr ?: "TBD"} ${nzDay(g.start)}"
                }
                TeamRow(t, lg.strength(t.id, out).net, recordText(lg, t.id), nextText)
            }
            HomeData(day, games, rows.groupBy { it.team.conference }.mapValues { (_, r) -> r.sortedByDescending { it.net } })
        }
    }
    val d = data ?: return Loading()
    LazyColumn(contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (d.games.isNotEmpty()) item {
            val today = LocalDate.now(Store.TZ)
            Panel(if (d.day == today) "Today's games" else "Next games · ${nzDay(d.games.first().game.start)}",
                note = LiveScores.updated?.let { "Scores from stats.nba.com, updated ${nzTime(it)}" }) {
                for (r in d.games) GameLine(lg, r.game, r.homeWin, r.homePts, r.awayPts) { nav.navigate("game/${r.game.id}") }
            }
        }
        for (conf in listOf("East", "West")) {
            item { Text("${conf}ern Conference", color = Theme.colors.text, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, modifier = Modifier.padding(top = 4.dp)) }
            items(d.conferences[conf].orEmpty(), key = { it.team.id }) { r ->
                Row(Modifier.fillMaxWidth().clickable { nav.navigate("team/${r.team.abbr}") }.padding(vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    TeamBadge(r.team, 36.dp)
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Body(r.team.name, weight = FontWeight.SemiBold)
                        Small(listOfNotNull(r.record.ifEmpty { null }, r.next).joinToString(" · "))
                    }
                    Text(signed(r.net), color = toneColor(if (r.net > 0) 1 else -1), fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                }
                Divider()
            }
        }
        item { Small("Teams are ordered by projected net rating (points per 100 possessions more than they allow), for the current roster without players marked unavailable.") }
    }
}

/** One game: teams, start time or score, and the prediction. */
@Composable
fun GameLine(lg: League, g: Game, homeWin: Double, homePts: Double, awayPts: Double, onClick: () -> Unit) {
    val c = Theme.colors
    val (status, awayScore, homeScore) = g.now()
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TeamBadge(lg.teams[g.awayId], 26.dp); Spacer(Modifier.width(6.dp))
                Body(lg.teams[g.awayId]?.abbr ?: "", weight = FontWeight.SemiBold)
                Body("  @  ", color = c.muted)
                TeamBadge(lg.teams[g.homeId], 26.dp); Spacer(Modifier.width(6.dp))
                Body(lg.teams[g.homeId]?.abbr ?: "", weight = FontWeight.SemiBold)
            }
            Small(buildString {
                append(if (status == 1) nzTime(g.start) else g.statusText())
                if (g.kind == "001") append(" · Preseason")
                if (g.sublabel.isNotEmpty()) append(" · ${g.sublabel}")
            })
        }
        Column(horizontalAlignment = Alignment.End) {
            if (status >= 2) {
                Text("$awayScore–$homeScore", color = c.text, fontWeight = FontWeight.Bold, fontSize = 17.sp)
                Small("Predicted ${whole(awayPts)}–${whole(homePts)}")
            } else {
                val fav = if (homeWin >= 0.5) lg.teams[g.homeId] else lg.teams[g.awayId]
                Text("${fav?.abbr} ${pct(maxOf(homeWin, 1 - homeWin))}", color = c.text, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                Small("${whole(awayPts)}–${whole(homePts)}", Modifier, c.muted)
            }
        }
    }
}

private data class Ratings(val off: Double, val def: Double, val net: Double, val pace: Double, val ranks: List<Int>)
private data class Fixture(val game: Game, val home: Boolean, val opp: Team?, val win: Double, val pts: Double, val oppPts: Double, val b2b: Boolean)
private data class TeamData(val ratings: Ratings, val upcoming: List<Fixture>, val results: List<Fixture>,
                            val roster: List<Pair<Player, Double>>, val out: Set<Long>)

/** A team: projected ratings, schedule with predictions, results and the roster (mark players out). */
@Composable
fun TeamScreen(nav: NavController, abbr: String) {
    val lg = rememberLeague() ?: return Loading()
    val team = lg.byAbbr[abbr] ?: return Loading("No team $abbr")
    val context = LocalContext.current
    val c = Theme.colors
    var tab by rememberSaveable { mutableStateOf("Upcoming") }
    val changes = Unavailable.changes
    val data by produceState<TeamData?>(null, lg, changes, LiveScores.updated) {
        value = withContext(Dispatchers.Default) {
            val out = Unavailable.effective(context, lg)
            val all = lg.teams.keys.associateWith { lg.strength(it, out) }
            fun rank(sel: (nz.jaredbro.nbastats.data.Strength) -> Double, higher: Boolean = true) =
                all.entries.sortedBy { if (higher) -sel(it.value) else sel(it.value) }.indexOfFirst { it.key == team.id } + 1
            val s = all.getValue(team.id)
            val ratings = Ratings(lg.leagueOrtg + s.off, lg.leagueOrtg - s.def, s.net, lg.leaguePace + s.pace,
                listOf(rank({ it.off }), rank({ it.def }), rank({ it.net }), rank({ it.pace })))
            val games = lg.schedule.filter { it.homeId == team.id || it.awayId == team.id }
            val upcoming = mutableListOf<Fixture>()
            val results = mutableListOf<Fixture>()
            for (g in games) {
                val home = g.homeId == team.id
                val opp = lg.teams[if (home) g.awayId else g.homeId]
                val (status, awayScore, homeScore) = g.now()
                if (status == 3) {
                    results += Fixture(g, home, opp, if ((if (home) homeScore - awayScore else awayScore - homeScore) > 0) 1.0 else 0.0,
                        (if (home) homeScore else awayScore).toDouble(), (if (home) awayScore else homeScore).toDouble(), false)
                } else if (opp != null) {
                    val p = lg.predict(g.homeId, g.awayId, lg.outFor(g.id, out), g.usDate, g.neutral)
                    upcoming += Fixture(g, home, opp, if (home) p.homeWin else 1 - p.homeWin,
                        if (home) p.home.pts else p.away.pts, if (home) p.away.pts else p.home.pts, if (home) p.home.b2b else p.away.b2b)
                }
            }
            val mins = lg.rotation(team.id, out)
            TeamData(ratings, upcoming, results.reversed(), lg.roster(team.id).sortedByDescending { (mins[it.id] ?: 0.0) * 1000 + it.mpg }
                .map { it to (mins[it.id] ?: 0.0) }, out)
        }
    }
    val d = data ?: return Loading()
    LazyColumn(contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TeamBadge(team, 48.dp); Spacer(Modifier.width(12.dp))
                Column {
                    Text(team.name, color = c.text, fontWeight = FontWeight.Bold, fontSize = 22.sp)
                    Small("${team.conference}ern Conference · ${recordText(lg, team.id)}")
                }
            }
        }
        item {
            val r = d.ratings
            Tiles(listOf(
                Tile("%.1f".format(r.off), "Offence (pts per 100)", sub = "#${r.ranks[0]} in the league"),
                Tile("%.1f".format(r.def), "Defence (allowed per 100)", sub = "#${r.ranks[1]} in the league"),
                Tile(signed(r.net), "Net rating", if (r.net > 0) 1 else -1, "#${r.ranks[2]} in the league"),
                Tile("%.1f".format(r.pace), "Pace", sub = "#${r.ranks[3]} fastest"),
            ))
        }
        item { ChipRow(listOf("Upcoming", "Results", "Roster"), tab, { it }) { tab = it } }
        when (tab) {
            "Upcoming" -> {
                if (d.upcoming.isEmpty()) item { Small("No games left on the schedule.") }
                items(d.upcoming, key = { it.game.id }) { f ->
                    Row(Modifier.fillMaxWidth().clickable { nav.navigate("game/${f.game.id}") }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Body(if (f.home) "vs " else "@ ", color = c.muted); TeamBadge(f.opp, 24.dp); Spacer(Modifier.width(6.dp))
                                Body(f.opp?.nickname ?: "TBD", weight = FontWeight.SemiBold)
                            }
                            Small("${nzDay(f.game.start)}, ${nzTime(f.game.start)}${if (f.b2b) " · back-to-back" else ""}${if (f.game.sublabel.isNotEmpty()) " · ${f.game.sublabel}" else ""}")
                        }
                        Column(horizontalAlignment = Alignment.End) {
                            Text(pct(f.win), color = toneColor(if (f.win >= 0.5) 1 else -1), fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                            Small("${whole(f.pts)}–${whole(f.oppPts)}")
                        }
                    }
                    Divider()
                }
            }
            "Results" -> {
                if (d.results.isEmpty()) item { Small("No games played yet this season.") }
                items(d.results, key = { it.game.id }) { f ->
                    Row(Modifier.fillMaxWidth().clickable { nav.navigate("game/${f.game.id}") }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Body(nzDay(f.game.start), Modifier.width(100.dp), color = c.text2)
                        Body(if (f.home) "vs " else "@ ", color = c.muted); TeamBadge(f.opp, 24.dp); Spacer(Modifier.width(6.dp))
                        Body(f.opp?.nickname ?: "", Modifier.weight(1f))
                        Text("${if (f.win > 0.5) "W" else "L"} ${f.pts.toInt()}–${f.oppPts.toInt()}", color = toneColor(if (f.win > 0.5) 1 else -1), fontWeight = FontWeight.SemiBold)
                    }
                    Divider()
                }
            }
            else -> {
                item {
                    Small("Expected minutes, per-game stats (this season once played, else last season) and impact (net points per 100 possessions with him on court). " +
                        "Switch a player off to leave him out of every prediction.")
                }
                items(d.roster, key = { it.first.id }) { (p, mins) ->
                    val season = if (p.perGame[lg.cur] != null) lg.cur else lg.prev
                    val pg = p.perGame[season]
                    val out = p.id in d.out
                    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f).clickable { nav.navigate("player/${p.id}") }) {
                            Body(p.name, color = if (out) c.muted else c.text, weight = FontWeight.SemiBold)
                            Small(listOfNotNull(p.position.ifEmpty { null }, if (mins > 0) "${whole(mins)} min" else "outside the rotation",
                                pg?.let { "${one(it["PTS"])} pts · ${one(it["REB"])} reb · ${one(it["AST"])} ast" } ?: "no NBA stats yet",
                                "impact ${signed(p.impact)}").joinToString(" · "))
                        }
                        Switch(!out, { Unavailable.set(context, lg, p.id, !it) },
                            colors = SwitchDefaults.colors(checkedTrackColor = c.accent))
                    }
                    Divider()
                }
            }
        }
    }
}
