package nz.jaredbro.nbastats.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavController
import nz.jaredbro.nbastats.data.League
import nz.jaredbro.nbastats.data.SavedPrediction
import nz.jaredbro.nbastats.data.Store
import nz.jaredbro.nbastats.data.Tracker
import kotlin.math.abs

/** The Mac's prediction tracker: each game's prediction saved before tip-off, scored once it's final. */
@Composable
fun PredictionsScreen(nav: NavController) {
    val lg = rememberLeague() ?: return Loading()
    val c = Theme.colors
    val kinds = Tracker.KIND_LABELS.keys.filter { k -> lg.saved.any { it.kind == k } }
    var kind by rememberSaveable { mutableStateOf<String?>(null) }
    var backfilled by rememberSaveable { mutableStateOf(true) }
    val chosen = kind?.takeIf { it in kinds } ?: kinds.firstOrNull() ?: "reg"
    LiveScores.updated  // re-score when live scores arrive

    // The final score: from the Mac's record, else from the game (live scores or the copied data) once it's over.
    val games = lg.games.associateBy { it.id }
    fun result(p: SavedPrediction): Pair<Int, Int>? = p.result ?: games[p.gameId]?.now()?.let { (status, away, home) ->
        if (status == 3) home to away else null
    }
    val mine = lg.saved.filter { it.kind == chosen && (backfilled || !it.backfilled) }.map { Tracker.Scored(it, result(it)) }
    val summary = Tracker.summary(mine)
    // Find games: team search (every word must match a team in the game), date, favourite's chance, right/wrong.
    var search by rememberSaveable { mutableStateOf("") }
    var day by rememberSaveable { mutableStateOf<String?>(null) }
    var minFav by rememberSaveable { mutableStateOf(0) }
    var outcome by rememberSaveable { mutableStateOf("All") }
    var sort by rememberSaveable { mutableStateOf(RESULT_SORTS[0].first) }
    val words = League.fold(search).split(" ").filter { it.isNotBlank() }
    fun teamText(id: Long) = lg.teams[id]?.let { League.fold("${it.abbr} ${it.name} ${it.nickname}") } ?: ""
    fun dayOf(s: Tracker.Scored) = s.p.start.atZone(Store.TZ).toLocalDate().toString()
    fun matches(s: Tracker.Scored): Boolean {
        val text = teamText(s.p.homeId) + " " + teamText(s.p.awayId)
        return words.all { it in text } && (day == null || dayOf(s) == day) &&
            100 * maxOf(s.p.homeWin, 1 - s.p.homeWin) >= minFav
    }
    val days = mine.map { it.p.start.atZone(Store.TZ).toLocalDate() }.distinct().sorted()
    val allFinished = mine.filter { it.result != null }
    val finished = allFinished.filter { matches(it) && (outcome == "All" || (it.correct == true) == (outcome == "Right")) }
        .let { list -> RESULT_SORTS.first { it.first == sort }.second(list) }
    val allUpcoming = mine.filter { it.result == null }
    val upcoming = allUpcoming.filter { matches(it) }.sortedBy { it.p.start }
    val filtering = words.isNotEmpty() || day != null || minFav > 0
    val tracked = lg.saved.map { it.gameId }.toSet()
    val untracked = lg.games.count { it.now().first == 3 && Tracker.kindOf(it.id) == chosen && it.id !in tracked }

    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Small("Each game's prediction is saved on your Mac before tip-off and scored once the game is final.") }
        if (kinds.size > 1) item { ChipRow(kinds, chosen, { Tracker.KIND_LABELS.getValue(it) }) { kind = it } }
        if (chosen == "pre") item {
            Banner("Preseason is scored separately: starters play short minutes and coaches test rotations, so these results say more about preseason than about the model.")
            if (lg.saved.any { it.kind == "pre" && it.backfilled }) Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Small("Include backfilled games (predicted afterwards, before any regular-season data)", Modifier.weight(1f))
                Switch(backfilled, { backfilled = it }, colors = SwitchDefaults.colors(checkedTrackColor = c.accent))
            }
        }
        if (summary == null) {
            item {
                Panel(null) {
                    Body(if (allUpcoming.isNotEmpty()) "No finished games with a saved prediction yet: the first results come in after ${nzDay(allUpcoming.minOf { it.p.start })}."
                         else "No saved predictions yet.")
                    if (untracked > 0) {
                        Spacer(Modifier.height(6.dp))
                        Body("$untracked finished game${if (untracked != 1) "s weren't" else " wasn't"} tracked: NBA Stats wasn't open on the Mac in the week before.")
                    }
                    Spacer(Modifier.height(6.dp))
                    Small(lg.howTracked)
                }
            }
        } else {
            item {
                Tiles(listOf(
                    Tile(pct(summary.accuracy), "Winners picked", sub = "${Math.round(summary.accuracy * summary.games)} of ${summary.games} games"),
                    Tile("%.1f".format(summary.marginError), "Average margin miss", sub = "points off the final margin"),
                    Tile("%.1f".format(summary.totalError), "Average total miss", sub = "points off the combined score"),
                    Tile("%.3f".format(summary.brier), "Brier score", sub = "0.25 = coin flip; lower is better"),
                ))
            }
            item {
                Panel("Do favourites win as often as predicted?",
                    note = "Bars show how often favourites won; the marker is how often they were expected to. With only a few games per row, expect big swings.") {
                    Cells(listOf("Favourite's chance", "Games", "Predicted", "Won"), listOf(1.6f, 0.8f, 1f, 1f), color = c.muted, size = 12.sp)
                    for (b in summary.bins) {
                        Cells(listOf("${(b.lo * 100).toInt()}–${minOf(100, (b.hi * 100).toInt())}%", "${b.games}", pct(b.expected), pct(b.rate)),
                            listOf(1.6f, 0.8f, 1f, 1f))
                        if (b.rate != null && b.expected != null) CalibrationBar(b.rate, b.expected)
                    }
                }
            }
            item {
                Panel("Coverage") {
                    Body("${summary.games} finished game${if (summary.games != 1) "s" else ""} scored" + if (untracked > 0) ", $untracked not tracked." else ".")
                    Spacer(Modifier.height(4.dp))
                    Small(lg.howTracked)
                }
            }
        }
        if (allUpcoming.isNotEmpty() || allFinished.isNotEmpty()) item {
            Panel("Find games") {
                OutlinedTextField(search, { search = it }, Modifier.fillMaxWidth(), label = { Text("Team") },
                    placeholder = { Text("e.g. Lakers, BOS") }, singleLine = true)
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Choice(day?.let { d -> nzDay(java.time.LocalDate.parse(d).atStartOfDay(Store.TZ).toInstant()) } ?: "All dates",
                        listOf("All dates") + days.map { nzDay(it.atStartOfDay(Store.TZ).toInstant()) }) { i ->
                        day = if (i == 0) null else days[i - 1].toString()
                    }
                    Choice(if (minFav == 0) "Any favourite" else "Favourite $minFav%+", FAV_MINS.map { if (it == 0) "Any favourite" else "Favourite $it%+" }) { i ->
                        minFav = FAV_MINS[i]
                    }
                }
                if (filtering) TextButton({ search = ""; day = null; minFav = 0 }) { Text("Clear", color = c.accent) }
            }
        }
        if (allUpcoming.isNotEmpty()) {
            item { Header("Upcoming", if (filtering) "${upcoming.size} of ${allUpcoming.size}" else "saved predictions, updated until tip-off") }
            if (upcoming.isEmpty()) item { Small("No upcoming games match.") }
            items(upcoming, key = { "u" + it.p.gameId }) { s -> SavedLine(lg, s) { nav.navigate("game/${s.p.gameId}") }; Divider() }
        }
        if (allFinished.isNotEmpty()) {
            item { Header("Results", if (filtering || outcome != "All") "${finished.size} of ${allFinished.size}" else null) }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Choice(if (outcome == "All") "Right and wrong" else outcome, listOf("Right and wrong", "Right", "Wrong")) { i ->
                        outcome = listOf("All", "Right", "Wrong")[i]
                    }
                    Choice(sort, RESULT_SORTS.map { it.first }) { i -> sort = RESULT_SORTS[i].first }
                }
            }
            if (finished.isEmpty()) item { Small("No results match.") }
            items(finished, key = { "f" + it.p.gameId }) { s -> SavedLine(lg, s) { nav.navigate("game/${s.p.gameId}") }; Divider() }
        }
        item { Small("Predictions are as of your last copy from the Mac; final scores come from stats.nba.com.") }
    }
}

private val FAV_MINS = listOf(0, 60, 70, 80)

/** Ways to order the results, as on the Mac's Tracker. */
private val RESULT_SORTS: List<Pair<String, (List<Tracker.Scored>) -> List<Tracker.Scored>>> = listOf(
    "Newest first" to { l -> l.sortedByDescending { it.p.start } },
    "Oldest first" to { l -> l.sortedBy { it.p.start } },
    "Biggest margin miss" to { l -> l.sortedByDescending { abs(it.marginError ?: 0.0) } },
    "Closest call" to { l -> l.sortedBy { abs(it.marginError ?: 0.0) } },
    "Biggest favourite" to { l -> l.sortedByDescending { maxOf(it.p.homeWin, 1 - it.p.homeWin) } },
)

@Composable
private fun Header(title: String, note: String?) {
    Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.Bottom) {
        Text(title, color = Theme.colors.text, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
        if (note != null) Small("  ·  $note")
    }
}

/** How often favourites won (filled bar) against how often they were expected to (marker). */
@Composable
private fun CalibrationBar(rate: Double, expected: Double) {
    val c = Theme.colors
    var width by androidx.compose.runtime.remember { mutableStateOf(0) }
    val density = LocalDensity.current
    Box(Modifier.fillMaxWidth().height(8.dp).padding(bottom = 2.dp).clip(RoundedCornerShape(4.dp)).background(c.grid).onSizeChanged { width = it.width }) {
        Box(Modifier.fillMaxWidth(rate.toFloat().coerceIn(0f, 1f)).fillMaxHeight().background(c.accent))
        Box(Modifier.offset(x = with(density) { (width * expected).toFloat().toDp() } - 1.dp).width(2.dp).fillMaxHeight().background(c.text))
    }
}

@Composable
private fun SavedLine(lg: League, s: Tracker.Scored, onClick: () -> Unit) {
    val c = Theme.colors
    val p = s.p
    val home = lg.teams[p.homeId]
    val away = lg.teams[p.awayId]
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TeamBadge(away, 26.dp); Spacer(Modifier.width(6.dp))
                Body(away?.abbr ?: "", weight = FontWeight.SemiBold)
                Body("  @  ", color = c.muted)
                TeamBadge(home, 26.dp); Spacer(Modifier.width(6.dp))
                Body(home?.abbr ?: "", weight = FontWeight.SemiBold)
            }
            Small(buildString {
                append(nzDay(p.start))
                if (s.result == null) append(", ${nzTime(p.start)}")
                append(" · predicted ${whole(p.awayPts)}–${whole(p.homePts)}")
                if (p.backfilled) append(" · backfilled")
            })
        }
        val fav = if (p.homeWin >= 0.5) home else away
        Spacer(Modifier.width(12.dp))
        Column(horizontalAlignment = Alignment.End) {
            val r = s.result
            if (r != null) {
                Text("${r.second}–${r.first}", color = c.text, fontWeight = FontWeight.Bold, fontSize = 17.sp)
                Text(if (s.correct == true) "✓ Right" else "✗ Wrong", color = toneColor(if (s.correct == true) 1 else -1), fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                Small("${fav?.abbr} ${pct(maxOf(p.homeWin, 1 - p.homeWin))} · miss ${signed(s.marginError)}")
            } else {
                Text("${fav?.abbr} ${pct(maxOf(p.homeWin, 1 - p.homeWin))}", color = c.text, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                val saved = runCatching { java.time.OffsetDateTime.parse(p.loggedAt).toInstant() }.getOrNull()
                if (saved != null) Small("updated ${nzDay(saved).substringBefore(" ")} ${nzTime(saved)}")
            }
        }
    }
}
