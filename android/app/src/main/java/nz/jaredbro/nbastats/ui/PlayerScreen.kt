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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavController
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import nz.jaredbro.nbastats.data.League
import nz.jaredbro.nbastats.data.Nba
import nz.jaredbro.nbastats.data.PairStats
import nz.jaredbro.nbastats.data.Shots
import java.time.LocalDate
import java.time.Period

private enum class MatchupSort(val label: String) { Possessions("Most possessions"), Best("Best first"), Worst("Worst first"), LowFg("Lowest FG%"), HighFg("Highest FG%") }

/** A player's card: bio, numbers, playstyle, plays like, shot chart, matchups and career. */
@Composable
fun PlayerScreen(nav: NavController, playerId: Long) {
    val lg = rememberLeague() ?: return Loading()
    val context = LocalContext.current
    val c = Theme.colors
    val p = lg.players[playerId]
    val info by produceState<Map<String, Any?>?>(null, playerId) { value = runCatching { Nba.playerInfo(context, playerId) }.getOrNull() }
    val career by produceState<List<Map<String, Any?>>?>(null, playerId) { value = runCatching { Nba.career(context, playerId) }.getOrDefault(emptyList()) }
    var estimate by remember { mutableStateOf<Pair<Long, Long>?>(null) }
    estimate?.let { (s, d) -> EstimateSheet(lg, s, d, onDismiss = { estimate = null }, onPlayer = { estimate = null; nav.navigate("player/$it") }) }

    Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        // Header
        Row(verticalAlignment = Alignment.CenterVertically) {
            AsyncImage("https://cdn.nba.com/headshots/nba/latest/260x190/$playerId.png", null,
                Modifier.size(width = 96.dp, height = 70.dp).clip(RoundedCornerShape(10.dp)), contentScale = ContentScale.Crop)
            Spacer(Modifier.width(12.dp))
            Column {
                Text(lg.nameOf(playerId), color = c.text, fontWeight = FontWeight.Bold, fontSize = 22.sp)
                val team = lg.teams[p?.teamId]
                Small(listOfNotNull(team?.name ?: "Not on an NBA roster", p?.position?.ifEmpty { null }, p?.number?.ifEmpty { null }?.let { "#$it" }).joinToString(" · "),
                    Modifier.clickable { team?.let { nav.navigate("team/${it.abbr}") } })
            }
        }
        info?.let { i ->
            val birth = (i["BIRTHDATE"] as? String)?.take(10)?.let { runCatching { LocalDate.parse(it) }.getOrNull() }
            Small(listOfNotNull(
                birth?.let { "Age ${Period.between(it, LocalDate.now()).years}" },
                (i["HEIGHT"] as? String)?.takeIf { it.contains("-") }?.let { h -> height(h.split("-").let { it[0].toInt() * 12.0 + it[1].toInt() }) },
                (i["WEIGHT"] as? String)?.takeIf { it.isNotEmpty() }?.let { "$it lb" },
                (i["COUNTRY"] as? String), (i["SCHOOL"] as? String)?.takeIf { it.isNotEmpty() },
                (i["DRAFT_YEAR"] as? String)?.let { if (it == "Undrafted") "Undrafted" else "Drafted $it, pick ${i["DRAFT_NUMBER"]}" },
            ).joinToString(" · "), color = c.text2)
        }

        if (p != null) {
            val season = if (p.perGame[lg.cur] != null) lg.cur else lg.prev
            p.perGame[season]?.let { pg ->
                Tiles(listOf(
                    Tile(one(pg["PTS"]), "Points ($season)"), Tile(one(pg["REB"]), "Rebounds"), Tile(one(pg["AST"]), "Assists"), Tile(one(pg["MIN"]), "Minutes"),
                    Tile(signed(p.impact), "Impact (net per 100)", if (p.impact > 0.5) 1 else if (p.impact < -0.5) -1 else 0, "off ${signed(p.impactOff)} · def ${signed(p.impactDef)}"),
                    Tile(signed(p.defRating?.times(100)), "Matchup defense", p.defRating?.let { if (it < -0.005) 1 else if (it > 0.005) -1 else 0 } ?: 0, "lower is better"),
                ))
            }
            if (p.summary != null) Panel("Playstyle${p.styleSeason?.let { " · $it" } ?: ""}") {
                Body(p.summary)
                for (t in p.traits) {
                    Spacer(Modifier.height(8.dp))
                    Body(t.label, weight = FontWeight.SemiBold)
                    Small(t.detail)
                }
            }
            if (p.similar.isNotEmpty()) Panel("Plays like", note = "Players whose game looks most like his: shot locations, usage, playmaking, efficiency, rebounding, blocks and steals.") {
                for ((id, match) in p.similar) {
                    Row(Modifier.fillMaxWidth().clickable { nav.navigate("player/$id") }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Body(lg.nameOf(id), Modifier.weight(1f))
                        Small("${(match * 100).toInt()}% match", color = c.text2)
                    }
                }
            }
        }

        ShotsPanel(lg, playerId, career)
        MatchupsPanel(lg, playerId, onPlayer = { nav.navigate("player/$it") }, onEstimate = { s, d -> estimate = s to d })

        career?.takeIf { it.isNotEmpty() }?.let { rows ->
            Panel("Regular season") {
                Cells(listOf("Season", "Team", "GP", "PTS", "REB", "AST", "FG%"), listOf(1.3f, 1f, 0.8f, 1f, 1f, 1f, 1f), color = c.text2, size = 12.sp)
                for (r in rows.reversed()) {
                    val fg = (r["FG_PCT"] as? Number)?.toDouble()
                    Cells(listOf("${r["SEASON_ID"]}", "${r["TEAM_ABBREVIATION"]}".replace("TOT", "Total"), "${r["GP"]}",
                        one((r["PTS"] as? Number)?.toDouble()), one((r["REB"] as? Number)?.toDouble()), one((r["AST"] as? Number)?.toDouble()), pct(fg, 1)),
                        listOf(1.3f, 1f, 0.8f, 1f, 1f, 1f, 1f), size = 13.sp)
                }
            }
        }
    }
}

@Composable
private fun ShotsPanel(lg: League, playerId: Long, career: List<Map<String, Any?>>?) {
    val context = LocalContext.current
    val seasons = remember(career) {
        career.orEmpty().map { "${it["SEASON_ID"]}" }.filter { it >= "1996-97" }.distinct().reversed()
    }
    var season by rememberSaveable(playerId) { mutableStateOf<String?>(null) }
    val chosen = season ?: seasons.firstOrNull()
    var opponent by rememberSaveable(playerId) { mutableStateOf<String?>(null) }
    val shots by produceState<Result<List<Shots.Shot>>?>(null, playerId, chosen) {
        value = null
        if (chosen != null) value = runCatching {
            val (rows, league) = Nba.shots(context, playerId, chosen, current = chosen >= lg.cur)
            withContext(Dispatchers.Default) { Shots.parse(rows, league) }
        }
    }
    Panel("Shot chart") {
        if (career == null) return@Panel Loading()
        if (seasons.isEmpty()) return@Panel Small("No NBA shots on record.")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            var open by remember { mutableStateOf(false) }
            Box {
                OutlinedButton({ open = true }) { Text(chosen ?: "", fontSize = 13.sp) }
                DropdownMenu(open, { open = false }) { for (s in seasons) DropdownMenuItem({ Text(s) }, { season = s; open = false }) }
            }
            val opponents = shots?.getOrNull()?.map { it.opponent }?.distinct()?.sorted().orEmpty()
            var openOpp by remember { mutableStateOf(false) }
            Box {
                OutlinedButton({ openOpp = true }) { Text(opponent?.let { "vs $it" } ?: "All opponents", fontSize = 13.sp) }
                DropdownMenu(openOpp, { openOpp = false }) {
                    DropdownMenuItem({ Text("All opponents") }, { opponent = null; openOpp = false })
                    for (o in opponents) DropdownMenuItem({ Text(o) }, { opponent = o; openOpp = false })
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        when (val r = shots) {
            null -> Loading("Downloading shots…")
            else -> r.fold({ list ->
                val filtered = if (opponent == null) list else list.filter { it.opponent == opponent }
                val chart = remember(filtered) { Shots.chart(filtered) }
                if (chart == null) Small("No shots for this selection.") else ShotChartView(chart)
            }, { Small("Couldn't load shots: ${it.message}") })
        }
    }
}

@Composable
private fun MatchupsPanel(lg: League, playerId: Long, onPlayer: (Long) -> Unit, onEstimate: (Long, Long) -> Unit) {
    val c = Theme.colors
    var guarding by rememberSaveable(playerId) { mutableStateOf(false) }
    var sort by rememberSaveable(playerId) { mutableStateOf(MatchupSort.Possessions) }
    var minPoss by rememberSaveable(playerId) { mutableStateOf(25) }
    var shown by rememberSaveable(playerId) { mutableStateOf(15) }
    val all by produceState<List<Pair<Long, PairStats>>?>(null, playerId, guarding) {
        value = withContext(Dispatchers.IO) { lg.matchups.allFor(playerId, guarding) }
    }
    Panel("Matchups · ${lg.matchups.firstSeason} to now") {
        ChipRow(listOf(false, true), guarding, { if (it) "Guarding" else "Guarded by" }) { guarding = it; shown = 15 }
        Spacer(Modifier.height(6.dp))
        ChipRow(MatchupSort.entries, sort, { it.label }) { sort = it }
        Spacer(Modifier.height(6.dp))
        ChipRow(listOf(0, 10, 25, 50, 100), minPoss, { if (it == 0) "Any" else "$it+ poss." }) { minPoss = it; shown = 15 }
        val list = all ?: return@Panel Loading()
        val rows = list.filter { it.second.poss >= minPoss }.let { rs ->
            when (sort) {
                MatchupSort.Possessions -> rs
                MatchupSort.Best -> rs.sortedBy { it.second.effect }
                MatchupSort.Worst -> rs.sortedByDescending { it.second.effect }
                MatchupSort.LowFg -> rs.filter { it.second.fga > 0 }.sortedBy { it.second.fgm.toDouble() / it.second.fga }
                MatchupSort.HighFg -> rs.filter { it.second.fga > 0 }.sortedByDescending { it.second.fgm.toDouble() / it.second.fga }
            }
        }
        Spacer(Modifier.height(6.dp))
        Small("${rows.size} ${if (guarding) "shooters he's guarded" else "defenders who've guarded him"}. Est. effect (per 100 possessions) is sample-adjusted; ${if (guarding) "negative means he held them below their usual" else "negative means they held him below his usual"}. Tap for the expected outcome.")
        Cells(listOf(if (guarding) "Shooter" else "Defender", "Poss.", "FG", "Pts", "Effect"), listOf(2.4f, 0.9f, 1.2f, 0.8f, 1f), color = c.text2, size = 12.sp)
        for ((other, s) in rows.take(shown)) {
            Cells(listOf(lg.nameOf(other), whole(s.poss), "${s.fgm}/${s.fga}", "${s.pts}", signed(s.effect * 100)), listOf(2.4f, 0.9f, 1.2f, 0.8f, 1f),
                colors = listOf(null, null, null, null, if (s.effect < -0.005) c.positive else if (s.effect > 0.005) c.negative else null),
                onClick = { if (guarding) onEstimate(other, playerId) else onEstimate(playerId, other) })
        }
        if (rows.size > shown) TextButton({ shown += 25 }) { Text("Show more") }
    }
}
