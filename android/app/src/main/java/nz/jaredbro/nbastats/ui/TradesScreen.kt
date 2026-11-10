package nz.jaredbro.nbastats.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import nz.jaredbro.nbastats.data.League
import nz.jaredbro.nbastats.data.Player
import nz.jaredbro.nbastats.data.SimTeam
import nz.jaredbro.nbastats.data.Simulator
import nz.jaredbro.nbastats.data.Team
import nz.jaredbro.nbastats.data.Unavailable
import kotlin.math.abs

private data class TeamRating(val off: Double, val def: Double, val net: Double, val netRank: Int)
private data class RotationRow(val id: Long, val name: String, val before: Double, val after: Double)
private data class TradeSide(
    val team: Team, val before: TeamRating, val after: TeamRating, val simBefore: SimTeam, val simAfter: SimTeam,
    val gets: List<Player>, val sends: List<Player>, val rotation: List<RotationRow>,
)

/** Ratings with everyone available, as the Mac's _team_ratings (offence and defence per 100, net rank). */
private fun ratings(lg: League): Map<Long, TeamRating> {
    val all = lg.teams.keys.associateWith { lg.strength(it, emptySet()) }
    val ranked = all.entries.sortedByDescending { it.value.net }.map { it.key }
    return all.mapValues { (t, s) -> TeamRating(lg.leagueOrtg + s.off, lg.leagueOrtg - s.def, s.net, ranked.indexOf(t) + 1) }
}

/** Tick the players each team sends; both teams' ratings, rotations and season odds are recalculated. */
@Composable
fun TradesScreen(nav: NavController) {
    val lg = rememberLeague() ?: return Loading()
    val context = LocalContext.current
    val c = Theme.colors
    val sorted = lg.teams.values.sortedBy { it.name }
    var a by rememberSaveable { mutableStateOf("LAL") }
    var b by rememberSaveable { mutableStateOf("OKC") }
    var ticked by rememberSaveable { mutableStateOf("") }    // ticked player ids, comma-separated
    var run by rememberSaveable { mutableStateOf("") }       // the ticks when "Run trade" was pressed
    val ta = lg.byAbbr[a] ?: sorted[0]
    val tb = lg.byAbbr[b]?.takeIf { it != ta } ?: sorted.first { it != ta }
    val sending = ticked.split(",").mapNotNull { it.toLongOrNull() }.toSet()

    val result by produceState<List<TradeSide>?>(null, lg, ta, tb, run) {
        value = null
        val ids = run.split(",").mapNotNull { it.toLongOrNull() }
        val moves = ids.mapNotNull { pid ->
            when (lg.players[pid]?.teamId) { ta.id -> pid to tb.id; tb.id -> pid to ta.id; else -> null }
        }.toMap()
        if (moves.isEmpty()) return@produceState
        value = withContext(Dispatchers.Default) {
            val after = lg.withTrade(moves)
            // Same assumption as the simulator's default: players on the unavailable list miss their next 10 games.
            val missing = Unavailable.effective(context, lg).associateWith<Long, Int?> { 10 }
            val sims = Simulator.run(lg, missing) to Simulator.run(after, missing)
            val r = ratings(lg) to ratings(after)
            listOf(ta, tb).map { t ->
                val rotBefore = lg.rotation(t.id, emptySet())
                val rotAfter = after.rotation(t.id, emptySet())
                val rotation = (rotBefore.keys + rotAfter.keys).sortedByDescending { maxOf(rotBefore[it] ?: 0.0, rotAfter[it] ?: 0.0) }
                    .map { RotationRow(it, lg.nameOf(it), rotBefore[it] ?: 0.0, rotAfter[it] ?: 0.0) }
                TradeSide(t, r.first.getValue(t.id), r.second.getValue(t.id),
                    sims.first.teams.first { it.team.id == t.id }, sims.second.teams.first { it.team.id == t.id },
                    moves.filterValues { it == t.id }.keys.map { lg.players.getValue(it) },
                    moves.filterValues { it != t.id }.keys.map { lg.players.getValue(it) }, rotation)
            }
        }
    }

    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Small("Tick the players each team sends. Both teams' ratings, rotations and season odds are recalculated with the trade. No salary-cap check: the NBA stats data doesn't include contracts.") }
        for ((side, team) in listOf("a" to ta, "b" to tb)) item {
            val other = if (team == ta) tb else ta
            Panel(null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TeamBadge(team, 32.dp); Spacer(Modifier.width(10.dp))
                    Choice(team.name, sorted.map { it.name }) { i ->
                        if (side == "a") a = sorted[i].abbr else b = sorted[i].abbr
                        ticked = ""; run = ""   // a new team starts a fresh trade
                    }
                }
                Spacer(Modifier.height(6.dp))
                Small("Sends to the ${other.nickname}:")
                for (p in lg.roster(team.id).sortedByDescending { it.mpg }) {
                    val on = p.id in sending
                    Row(Modifier.fillMaxWidth().clickable { ticked = (if (on) sending - p.id else sending + p.id).joinToString(",") },
                        verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(on, null, colors = CheckboxDefaults.colors(checkedColor = c.accent))
                        Spacer(Modifier.width(6.dp))
                        Column(Modifier.weight(1f).padding(vertical = 4.dp)) {
                            Body(p.name)
                            Small("${p.position.ifEmpty { "–" }} · ${whole(p.mpg)} min · impact ${signed(p.impact)}")
                        }
                    }
                }
            }
        }
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Button({ run = sending.joinToString(",") }, enabled = sending.isNotEmpty(),
                    colors = ButtonDefaults.buttonColors(containerColor = c.accent)) { Text("Run trade") }
                if (sending.isNotEmpty()) TextButton({ ticked = ""; run = "" }) { Text("Clear", color = c.text2) }
            }
        }
        val sides = result
        when {
            run.isEmpty() -> item { Panel(null) { Small("Tick at least one player and press Run trade.") } }
            sides == null -> item { Loading("Re-rating both teams and simulating the season…") }
            else -> {
                for (s in sides) item { SideResult(s, nav) }
                item {
                    Small("Ratings keep each team's starting point and count the traded players in full (like marking a player out, or in): " +
                        "incoming players take minutes in the rotation and the team's rating moves by each player's estimated impact times his " +
                        "change in minutes. Season odds come from 10,000 simulated seasons, with players on your unavailable list missing their next 10 games.")
                }
            }
        }
    }
}

@Composable
private fun SideResult(s: TradeSide, nav: NavController) {
    val c = Theme.colors
    Panel(null) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TeamBadge(s.team, 32.dp); Spacer(Modifier.width(10.dp))
            Text(s.team.name, color = c.text, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
        }
        Spacer(Modifier.height(6.dp))
        if (s.gets.isNotEmpty()) Body("Gets " + s.gets.joinToString(", ") { it.name })
        if (s.sends.isNotEmpty()) Body("Sends " + s.sends.joinToString(", ") { it.name }, color = c.text2)
        Spacer(Modifier.height(8.dp))
        val w = listOf(1.5f, 1f, 1f, 0.9f)
        Cells(listOf("", "Before", "After", "Change"), w, color = c.muted, size = 12.sp)
        ChangeRow("Net rating", "${signed(s.before.net)} #${s.before.netRank}", "${signed(s.after.net)} #${s.after.netRank}", s.after.net - s.before.net, signed(s.after.net - s.before.net), w)
        ChangeRow("Offence", one(s.before.off), one(s.after.off), s.after.off - s.before.off, signed(s.after.off - s.before.off), w)
        ChangeRow("Defence", one(s.before.def), one(s.after.def), s.before.def - s.after.def, signed(s.after.def - s.before.def), w)  // lower is better
        Divider()
        ChangeRow("Record", "${whole(s.simBefore.wins)}–${whole(s.simBefore.losses)}", "${whole(s.simAfter.wins)}–${whole(s.simAfter.losses)}",
            s.simAfter.wins - s.simBefore.wins, signed(s.simAfter.wins - s.simBefore.wins) + " W", w)
        for ((label, before, after) in listOf(Triple("Playoffs", s.simBefore.playoffs, s.simAfter.playoffs),
            Triple("Finals", s.simBefore.finals, s.simAfter.finals), Triple("Title", s.simBefore.title, s.simAfter.title))) {
            val diff = 100 * (after - before)
            ChangeRow(label, pct(before, if (label == "Title") 1 else 0), pct(after, if (label == "Title") 1 else 0), diff / 10, "${signed(diff, 0)} pts", w)
        }
        Spacer(Modifier.height(12.dp))
        Text("Rotation", color = c.text, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
        Small("expected minutes")
        val rw = listOf(2f, 1f, 1f)
        Cells(listOf("Player", "Before", "After"), rw, color = c.muted, size = 12.sp)
        for (r in s.rotation) {
            val color = when { r.before == 0.0 && r.after > 0 -> c.positive; r.before > 0 && r.after == 0.0 -> c.negative; else -> null }
            Cells(listOf(r.name, if (r.before > 0) whole(r.before) else "–", if (r.after > 0) whole(r.after) else "–"), rw,
                colors = listOf(color, null, null), size = 13.sp) { nav.navigate("player/${r.id}") }
        }
    }
}

/** A before/after row; [good] is positive when the change helps (coloured if it's more than a rounding blip). */
@Composable
private fun ChangeRow(label: String, before: String, after: String, good: Double, change: String, w: List<Float>) {
    val tone: Color? = if (abs(good) > 0.05) toneColor(if (good > 0) 1 else -1) else null
    Cells(listOf(label, before, after, change), w, size = 13.sp, colors = listOf(null, Theme.colors.text2, null, tone))
}
