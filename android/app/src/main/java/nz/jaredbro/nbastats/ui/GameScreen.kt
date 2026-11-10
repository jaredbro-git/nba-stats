package nz.jaredbro.nbastats.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
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
import nz.jaredbro.nbastats.data.MatchupRow
import nz.jaredbro.nbastats.data.Nba
import nz.jaredbro.nbastats.data.Prediction
import nz.jaredbro.nbastats.data.Side
import nz.jaredbro.nbastats.data.Unavailable

/** A game: prediction, why, expected box scores with Out toggles, matchups, and the real box score once it starts. */
@Composable
fun GameScreen(nav: NavController, gameId: String) {
    val lg = rememberLeague() ?: return Loading()
    val g = lg.games.firstOrNull { it.id == gameId } ?: return Loading("Game not found")
    val context = LocalContext.current
    val c = Theme.colors
    val rosterIds = remember(lg, g) { (lg.roster(g.homeId) + lg.roster(g.awayId)).map { it.id }.toSet() }
    // The game's own list from the Mac if it has one, else your list.
    val saved = remember(lg, Unavailable.changes) { lg.outFor(g.id, Unavailable.effective(context, lg)) intersect rosterIds }
    var out by remember(saved) { mutableStateOf(saved) }
    var overrides by remember { mutableStateOf(mapOf<Long, Long>()) }
    var estimate by remember { mutableStateOf<Pair<Long, Long>?>(null) }
    val p by produceState<Prediction?>(null, lg, out, overrides) {
        value = withContext(Dispatchers.Default) { lg.predict(g.homeId, g.awayId, out, g.usDate, g.neutral, overrides, withMatchups = true) }
    }
    val (status, awayScore, homeScore) = g.now()
    var box by remember { mutableStateOf<Map<Long, List<Nba.BoxLine>>?>(null) }
    var boxError by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(gameId, status, LiveScores.updated) {
        if (status >= 2) runCatching { box = Nba.boxScore(context, gameId, if (status == 2) 45_000 else Nba.DAY) }
            .onFailure { boxError = it.message }
    }
    val home = lg.teams[g.homeId]
    val away = lg.teams[g.awayId]

    estimate?.let { (s, d) -> EstimateSheet(lg, s, d, onDismiss = { estimate = null }, onPlayer = { estimate = null; nav.navigate("player/$it") }) }

    Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Small(buildString {
            append(if (g.kind == "001") "Preseason" else if (g.kind == "004") "Playoffs" else "Regular season")
            if (g.sublabel.isNotEmpty()) append(" · ${g.sublabel}")
            append(" · ${nzDay(g.start)}, ${nzTime(g.start)} NZ")
            if (g.arena.isNotEmpty()) append(" · ${g.arena}, ${g.city}")
        })
        if (status >= 2) Banner("${if (status == 2) "Live: " else "Final: "}${away?.nickname} $awayScore – $homeScore ${home?.nickname}  ·  ${g.statusText()}")

        val pred = p ?: return@Column Loading()
        Panel(null) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                for ((side, team, win) in listOf(Triple(pred.away, away, 1 - pred.homeWin), Triple(pred.home, home, pred.homeWin))) {
                    Column(Modifier.weight(1f).clickable { team?.let { nav.navigate("team/${it.abbr}") } }, horizontalAlignment = Alignment.CenterHorizontally) {
                        TeamBadge(team, 44.dp)
                        Small(team?.nickname ?: "", color = c.text)
                        Text(whole(side.pts), color = c.text, fontWeight = FontWeight.Bold, fontSize = 36.sp)
                        Small("${pct(win)} to win")
                    }
                    if (side === pred.away) Text("@", color = c.muted, fontSize = 18.sp)
                }
            }
            Spacer(Modifier.height(12.dp))
            WinBar(1 - pred.homeWin)
            Spacer(Modifier.height(6.dp))
            Small("Expected margin: ${if (pred.margin > 0) home?.nickname else away?.nickname} by ${"%.1f".format(kotlin.math.abs(pred.margin))} · ${whole(pred.pace)} possessions",
                color = c.text2)
        }

        Panel("How the margin is built", note = "Points to the ${home?.nickname}. Real results land within about ±13 points of the expected margin two times in three.") {
            for ((label, v) in pred.factors) Cells(listOf(label, signed(v)), listOf(3f, 1f),
                colors = listOf(null, if (v > 0.05) c.positive else if (v < -0.05) c.negative else null))
            Divider()
            Cells(listOf("Expected margin", signed(pred.margin)), listOf(3f, 1f), bold = true)
        }

        Panel("Team comparison") {
            Cells(listOf("", away?.abbr ?: "", home?.abbr ?: ""), listOf(2f, 1f, 1f), color = c.text2)
            fun ratings(side: Side) = Triple(lg.leagueOrtg + side.strength.off, lg.leagueOrtg - side.strength.def, side.strength.net)
            val ar = ratings(pred.away); val hr = ratings(pred.home)
            Cells(listOf("Record", recordText(lg, g.awayId).removeSuffix(" last season"), recordText(lg, g.homeId).removeSuffix(" last season")), listOf(2f, 1f, 1f))
            Cells(listOf("Offence", one(ar.first), one(hr.first)), listOf(2f, 1f, 1f))
            Cells(listOf("Defence (lower is better)", one(ar.second), one(hr.second)), listOf(2f, 1f, 1f))
            Cells(listOf("Net rating", signed(ar.third), signed(hr.third)), listOf(2f, 1f, 1f))
            Cells(listOf("Pace", one(lg.leaguePace + pred.away.strength.pace), one(lg.leaguePace + pred.home.strength.pace)), listOf(2f, 1f, 1f))
            Cells(listOf("Back-to-back", if (pred.away.b2b) "Yes" else "No", if (pred.home.b2b) "Yes" else "No"), listOf(2f, 1f, 1f))
        }

        if (out != saved) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Small("Changes here apply to this game only.", Modifier.weight(1f))
                TextButton({
                    for (pid in rosterIds) if ((pid in out) != (pid in saved)) Unavailable.set(context, lg, pid, pid in out)
                }) { Text("Save for all games") }
            }
        }
        for (side in listOf(pred.away, pred.home)) {
            ExpectedBox(lg, side, out, onToggle = { pid -> out = if (pid in out) out - pid else out + pid }, onPlayer = { nav.navigate("player/$it") })
        }

        pred.matchups.let { mu ->
            Panel("Matchups", note = "Each side's main scorers and the defender most likely to guard them. Pick another defender to see how the prediction changes.") {
                for (key in listOf("away", "home")) {
                    val (rows, defenders) = mu[key] ?: continue
                    val team = lg.teams[if (key == "away") g.awayId else g.homeId]
                    Small("${team?.nickname} scorers", color = c.text2)
                    for (r in rows) MatchupLine(lg, r, defenders,
                        onPick = { d -> overrides = overrides + (r.shooter.id to d) },
                        onEstimate = { if (r.chosen != 0L) estimate = r.shooter.id to r.chosen })
                    Spacer(Modifier.height(8.dp))
                }
                if (overrides.isNotEmpty()) TextButton({ overrides = emptyMap() }) { Text("Reset to likely matchups") }
            }
        }

        if (status >= 2) {
            Panel(if (status == 2) "Box score (live)" else "Box score") {
                val b = box
                when {
                    b != null -> for (tid in listOf(g.awayId, g.homeId)) {
                        Small(lg.teams[tid]?.nickname ?: "", color = c.text2)
                        Cells(listOf("Player", "MIN", "PTS", "REB", "AST", "+/−"), listOf(3f, 1f, 1f, 1f, 1f, 1f), color = c.text2, size = 12.sp)
                        for (l in b[tid].orEmpty()) Cells(listOf(l.name, l.minutes.substringBefore(":"), "${l.pts}", "${l.reb}", "${l.ast}", signed(l.plusMinus, 0)),
                            listOf(3f, 1f, 1f, 1f, 1f, 1f), onClick = { nav.navigate("player/${l.playerId}") })
                        Spacer(Modifier.height(8.dp))
                    }
                    boxError != null -> Small("Couldn't load the box score: $boxError")
                    else -> Loading()
                }
            }
        }
    }
}

@Composable
private fun ExpectedBox(lg: League, side: Side, out: Set<Long>, onToggle: (Long) -> Unit, onPlayer: (Long) -> Unit) {
    val c = Theme.colors
    val team = lg.teams[side.teamId]
    Panel("${team?.nickname} · expected") {
        Cells(listOf("Out  Player", "MIN", "PTS", "REB", "AST"), listOf(3.4f, 1f, 1f, 1f, 1f), color = c.text2, size = 12.sp)
        for (l in side.lines) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(false, { onToggle(l.player.id) }, colors = CheckboxDefaults.colors(uncheckedColor = c.muted))
                Box(Modifier.weight(1f).clickable { onPlayer(l.player.id) }) {
                    Cells(listOf(l.player.name, whole(l.min), one(l["PTS"]), one(l["REB"]), one(l["AST"])), listOf(2.6f, 1f, 1f, 1f, 1f))
                }
            }
        }
        val playing = side.lines.map { it.player.id }.toSet()
        for (p in lg.roster(side.teamId).filter { it.id !in playing }.sortedWith(compareBy({ it.id !in out }, { -it.mpg }))) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(p.id in out, { onToggle(p.id) }, colors = CheckboxDefaults.colors(checkedColor = c.negative, uncheckedColor = c.muted))
                Small("${p.name} · ${if (p.id in out) "Out" else "outside the rotation"}", Modifier.weight(1f).clickable { onPlayer(p.id) },
                    color = if (p.id in out) c.negative else c.muted)
            }
        }
        Cells(listOf("Team", "240", one(side.pts), one(side.lines.sumOf { it["REB"] }), one(side.lines.sumOf { it["AST"] })),
            listOf(3.4f, 1f, 1f, 1f, 1f), bold = true)
    }
}

@Composable
private fun MatchupLine(lg: League, r: MatchupRow, defenders: List<Long>, onPick: (Long) -> Unit, onEstimate: () -> Unit) {
    val c = Theme.colors
    var open by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Body(r.shooter.name, Modifier.weight(1f), weight = FontWeight.SemiBold)
            Body("${one(r.pts)} pts", weight = FontWeight.SemiBold)
            if (r.changed && kotlin.math.abs(r.change) >= 0.05) Small(" (${signed(r.change)})", color = if (r.change > 0) c.positive else c.negative)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Small("Guarded by ", color = c.text2)
            Box {
                OutlinedButton({ open = true }) {
                    Text((if (r.chosen == 0L) "No specific defender" else lg.players[r.chosen]?.name ?: "?") + if (!r.changed) " (likely)" else "", fontSize = 13.sp)
                }
                DropdownMenu(open, { open = false }) {
                    for (d in defenders) DropdownMenuItem(text = { Text((lg.players[d]?.name ?: "$d") + if (d == r.likely) " (likely)" else "") },
                        onClick = { open = false; onPick(d) })
                    DropdownMenuItem(text = { Text("No specific defender") }, onClick = { open = false; onPick(0L) })
                }
            }
            if (r.chosen != 0L) TextButton(onEstimate) { Text("Expected", fontSize = 13.sp) }
        }
        val h = r.history
        Small(when {
            h != null -> "${h.fgm}/${h.fga} FG, ${h.pts} pts on ${whole(h.poss)} possessions in ${h.gp} games against each other. Est. ${signed(r.vsAverage)} pts vs an average defender."
            r.chosen != 0L -> "Never matched up: uses ${lg.players[r.chosen]?.name}'s defensive rating. Est. ${signed(r.vsAverage)} pts vs an average defender."
            else -> "Team defense, no specific defender."
        })
    }
}
