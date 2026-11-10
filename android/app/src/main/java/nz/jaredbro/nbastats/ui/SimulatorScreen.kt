package nz.jaredbro.nbastats.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import nz.jaredbro.nbastats.data.League
import nz.jaredbro.nbastats.data.SimResult
import nz.jaredbro.nbastats.data.SimTeam
import nz.jaredbro.nbastats.data.Simulator
import nz.jaredbro.nbastats.data.Unavailable

/** How many games a player misses: a number of games, or null for the rest of the season. */
private val MISS_CHOICES: List<Pair<Int?, String>> = listOf(5 to "next 5 games", 10 to "next 10 games", 20 to "next 20 games",
    41 to "next 41 games", null to "rest of season")
private val SAVED_CHOICES = listOf("0" to "Play every game", "5" to "Miss their next 5 games", "10" to "Miss their next 10 games",
    "20" to "Miss their next 20 games", "rest" to "Miss the rest of the season")

/** "203999:20,1628983:rest" <-> {203999: 20, 1628983: null}, so the what-ifs survive rotation and navigation. */
private fun parseMissing(text: String): Map<Long, Int?> = text.split(",").mapNotNull { part ->
    val (id, games) = part.split(":").takeIf { it.size == 2 } ?: return@mapNotNull null
    id.toLongOrNull()?.let { it to games.toIntOrNull() }
}.toMap()

private fun formatMissing(m: Map<Long, Int?>) = m.entries.joinToString(",") { "${it.key}:${it.value ?: "rest"}" }

/** Your unavailable list (missing their next `saved` games) plus the what-ifs. */
fun missingFor(out: Set<Long>, saved: String, scenario: Map<Long, Int?>): Map<Long, Int?> {
    val games = if (saved == "rest") null else saved.toIntOrNull() ?: 10
    val missing = if (saved == "0") HashMap() else out.associateWith { games }.toMutableMap()
    missing.putAll(scenario)
    return missing
}

/** The rest of the season, the play-in and the playoffs, played 10,000 times on the phone. */
@Composable
fun SimulatorScreen(nav: NavController) {
    val lg = rememberLeague() ?: return Loading()
    val context = LocalContext.current
    val c = Theme.colors
    var saved by rememberSaveable { mutableStateOf("10") }
    var scenarioText by rememberSaveable { mutableStateOf("") }
    val scenario = parseMissing(scenarioText)
    val changes = Unavailable.changes
    val savedCount = Unavailable.effective(context, lg).size
    val result by produceState<SimResult?>(null, lg, saved, scenarioText, changes) {
        value = null
        value = withContext(Dispatchers.Default) { Simulator.run(lg, missingFor(Unavailable.effective(context, lg), saved, scenario)) }
    }
    var expanded by remember { mutableStateOf<Long?>(null) }

    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Small(result?.let { "The rest of the season, the play-in and the playoffs, played ${"%,d".format(it.sims)} times with the game model (${it.gamesLeft} regular-season games left)." }
                ?: "Playing the rest of the season 10,000 times…")
        }
        item {
            Panel("What if…") {
                Small("Players on your unavailable list ($savedCount)")
                Spacer(Modifier.height(6.dp))
                Choice(SAVED_CHOICES.first { it.first == saved }.second, SAVED_CHOICES.map { it.second }) { i -> saved = SAVED_CHOICES[i].first }
                for ((pid, games) in scenario) {
                    Spacer(Modifier.height(10.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f).clickable { nav.navigate("player/$pid") }) {
                            Body(lg.nameOf(pid), weight = FontWeight.SemiBold)
                            Small(lg.players[pid]?.teamId?.let { lg.teams[it]?.abbr } ?: "")
                        }
                        Choice("misses " + MISS_CHOICES.first { it.first == games }.second, MISS_CHOICES.map { "misses " + it.second }) { i ->
                            scenarioText = formatMissing(scenario + (pid to MISS_CHOICES[i].first))
                        }
                        TextButton({ scenarioText = formatMissing(scenario - pid) }) { Text("Remove", color = c.text2) }
                    }
                }
                Spacer(Modifier.height(10.dp))
                PlayerPicker(lg, "Add a player who misses games") { pid ->
                    if (pid !in scenario) scenarioText = formatMissing(scenario + (pid to 10))
                }
                if (scenario.isNotEmpty()) TextButton({ scenarioText = "" }) { Text("Clear what-ifs", color = c.accent) }
            }
        }
        val r = result
        if (r == null) {
            item { Loading("Simulating 10,000 seasons…") }
            return@LazyColumn
        }
        item {
            Tiles(r.teams.sortedByDescending { it.title }.take(4).map {
                Tile(pct(it.title, 1), it.team.nickname, sub = "title · ${whole(it.wins)} wins")
            })
        }
        for (conf in listOf("East", "West")) {
            val teams = r.teams.filter { it.team.conference == conf }.sortedByDescending { it.wins }
            item {
                Panel("${conf}ern Conference", note = "Tap a team for its full odds. Lines mark 6th (playoffs) and 10th (play-in).") {
                    Cells(listOf("Team", "Projected", "Playoffs", "Title"), WEIGHTS, color = c.muted, size = 12.sp)
                    teams.forEachIndexed { i, t ->
                        SimRow(t, expanded == t.team.id) { expanded = if (expanded == t.team.id) null else t.team.id }
                        if (expanded == t.team.id) SimDetail(t) { nav.navigate("team/${t.team.abbr}") }
                        if (i == 5 || i == 9) Box(Modifier.fillMaxWidth().height(2.dp).background(c.text2)) else Divider()
                    }
                }
            }
        }
        item {
            Small("How it works: every remaining game gets a win chance from the game model, with players marked out for the games they miss. " +
                "Each simulated season also draws every team's true strength from a spread of ±${"%.1f".format(r.teamSd)} points around its projection " +
                "(wider before the season, narrower as games are played), so long-shot runs happen about as often as they do in reality. " +
                "Top six make the playoffs; 7–10 go to the play-in. Series are best of seven, higher seed hosting games 1, 2, 5 and 7. " +
                "Players out for the rest of the season also miss the playoffs. Games not on the schedule yet (NBA Cup knockouts) are played " +
                "against a league-average opponent at a neutral site, so every team plays 82.")
        }
    }
}

private val WEIGHTS = listOf(1.7f, 1.1f, 0.9f, 0.8f)

/** A share as the Mac shows it: ">99%", "<1%", or "–" for never. */
private fun odds(v: Double): String = when {
    v >= 0.995 -> ">99%"
    v == 0.0 -> "–"
    v < 0.005 -> "<1%"
    else -> pct(v)
}

@Composable
private fun SimRow(t: SimTeam, open: Boolean, onClick: () -> Unit) {
    val c = Theme.colors
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Row(Modifier.weight(WEIGHTS[0]), verticalAlignment = Alignment.CenterVertically) {
            TeamBadge(t.team, 24.dp); Spacer(Modifier.width(8.dp))
            Column {
                Text(t.team.nickname, color = c.text, fontSize = 14.sp, fontWeight = if (open) FontWeight.SemiBold else null, maxLines = 1)
                Small("now ${t.record.first}–${t.record.second}")
            }
        }
        Text("${whole(t.wins)}–${whole(t.losses)}", Modifier.weight(WEIGHTS[1]), color = c.text, fontWeight = FontWeight.SemiBold,
            fontSize = 14.sp, textAlign = androidx.compose.ui.text.style.TextAlign.End)
        Text(odds(t.playoffs), Modifier.weight(WEIGHTS[2]), color = c.text, fontSize = 14.sp, textAlign = androidx.compose.ui.text.style.TextAlign.End)
        Text(odds(t.title), Modifier.weight(WEIGHTS[3]), color = c.text, fontSize = 14.sp, textAlign = androidx.compose.ui.text.style.TextAlign.End)
    }
}

@Composable
private fun SimDetail(t: SimTeam, onTeam: () -> Unit) {
    val w = listOf(1.4f, 1f)
    Column(Modifier.fillMaxWidth().padding(start = 32.dp, bottom = 8.dp)) {
        Cells(listOf("80% range", "${t.low}–${t.high} wins"), w, size = 13.sp)
        for ((label, v) in listOf("#1 seed" to t.seed1, "Top 6" to t.top6, "Play-in" to t.playin, "Make playoffs" to t.playoffs,
            "2nd round" to t.round2, "Conference finals" to t.confFinals, "Finals" to t.finals, "Title" to t.title)) {
            Cells(listOf(label, odds(v)), w, size = 13.sp)
        }
        TextButton(onTeam) { Text("Open ${t.team.nickname} →", color = Theme.colors.accent) }
    }
}

/** A dropdown button showing the current choice; [onPick] gets the chosen index. */
@Composable
fun Choice(current: String, options: List<String>, onPick: (Int) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        OutlinedButton({ open = true }) { Text(current, fontSize = 13.sp, maxLines = 1) }
        DropdownMenu(open, { open = false }) {
            options.forEachIndexed { i, o -> DropdownMenuItem({ Text(o) }, { onPick(i); open = false }) }
        }
    }
}

/** Search for a rostered player by name. */
@Composable
fun PlayerPicker(lg: League, label: String, onPick: (Long) -> Unit) {
    var text by rememberSaveable { mutableStateOf("") }
    OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth(), label = { Text(label) }, singleLine = true)
    val matches = remember(text) { lg.search(text, 30).filter { lg.players[it.first]?.teamId != null }.take(6) }
    for ((pid, name) in matches) {
        Row(Modifier.fillMaxWidth().clickable { onPick(pid); text = "" }.padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Body(name, Modifier.weight(1f))
            Small(lg.players[pid]?.teamId?.let { lg.teams[it]?.abbr } ?: "")
        }
    }
}
