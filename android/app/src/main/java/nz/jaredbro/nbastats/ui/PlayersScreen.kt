package nz.jaredbro.nbastats.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavController
import nz.jaredbro.nbastats.data.League
import nz.jaredbro.nbastats.data.Player

private enum class Sort(val label: String, val ascending: Boolean = false) {
    Points("Points"), Impact("Impact"), Defense("Matchup D", ascending = true), Shooting("True shooting"), Usage("Usage"),
    Minutes("Minutes"), Youngest("Youngest", ascending = true),
}

private val GROUP = mapOf("G" to "Guards", "G-F" to "Guards", "F-G" to "Wings", "F" to "Wings", "F-C" to "Bigs", "C-F" to "Bigs", "C" to "Bigs")

private fun Player.line(lg: League) = perGame[lg.cur] ?: perGame[lg.prev]

private fun Player.sortValue(lg: League, sort: Sort): Double? = when (sort) {
    Sort.Points -> line(lg)?.get("PTS")
    Sort.Impact -> impact
    Sort.Defense -> defRating?.times(100)
    Sort.Shooting -> ts
    Sort.Usage -> usg
    Sort.Minutes -> line(lg)?.get("MIN")
    Sort.Youngest -> age
}

/** Every rostered player, sortable and filterable, plus a search for anyone (retired players included). */
@Composable
fun PlayersScreen(nav: NavController) {
    val lg = rememberLeague() ?: return Loading()
    val c = Theme.colors
    var query by rememberSaveable { mutableStateOf("") }
    var sort by rememberSaveable { mutableStateOf(Sort.Points) }
    var team by rememberSaveable { mutableStateOf<String?>(null) }
    var group by rememberSaveable { mutableStateOf("All") }
    var minMinutes by rememberSaveable { mutableStateOf(20) }
    val rows = remember(lg, query, sort, team, group, minMinutes) {
        val words = League.fold(query).split(" ").filter { it.isNotBlank() }
        lg.players.values.asSequence()
            .filter { it.teamId != null }
            .filter { team == null || lg.teams[it.teamId]?.abbr == team }
            .filter { group == "All" || GROUP[it.position] == group }
            .filter { (it.line(lg)?.get("MIN") ?: 0.0) >= minMinutes || words.isNotEmpty() }
            .filter { p -> words.all { it in League.fold(p.name) } }
            .sortedWith(compareBy<Player> { it.sortValue(lg, sort) == null }.thenBy {
                val v = it.sortValue(lg, sort) ?: 0.0
                if (sort.ascending) v else -v
            })
            .toList()
    }
    val others = remember(lg, query) { if (query.length >= 2) lg.search(query).filter { (id, _) -> lg.players[id]?.teamId == null } else emptyList() }

    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item {
            OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), label = { Text("Find a player") }, singleLine = true)
        }
        item { ChipRow(Sort.entries, sort, { it.label }) { sort = it } }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                var open by remember { mutableStateOf(false) }
                Box {
                    OutlinedButton({ open = true }) { Text(team ?: "All teams", fontSize = 13.sp) }
                    DropdownMenu(open, { open = false }) {
                        DropdownMenuItem({ Text("All teams") }, { team = null; open = false })
                        for (t in lg.teams.values.sortedBy { it.name }) DropdownMenuItem({ Text(t.name) }, { team = t.abbr; open = false })
                    }
                }
                var openGroup by remember { mutableStateOf(false) }
                Box {
                    OutlinedButton({ openGroup = true }) { Text(group, fontSize = 13.sp) }
                    DropdownMenu(openGroup, { openGroup = false }) {
                        for (g in listOf("All", "Guards", "Wings", "Bigs")) DropdownMenuItem({ Text(g) }, { group = g; openGroup = false })
                    }
                }
                var openMin by remember { mutableStateOf(false) }
                Box {
                    OutlinedButton({ openMin = true }) { Text(if (minMinutes == 0) "Any minutes" else "$minMinutes+ min", fontSize = 13.sp) }
                    DropdownMenu(openMin, { openMin = false }) {
                        for (m in listOf(0, 10, 20, 28)) DropdownMenuItem({ Text(if (m == 0) "Any minutes" else "$m+ min") }, { minMinutes = m; openMin = false })
                    }
                }
            }
        }
        item { Small("${rows.size} players · ${sort.label}${if (sort == Sort.Defense) " (points per 100 his matchups score vs usual; lower is better)" else ""}") }
        items(rows, key = { it.id }) { p ->
            val line = p.line(lg)
            Row(Modifier.fillMaxWidth().clickable { nav.navigate("player/${p.id}") }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                TeamBadge(lg.teams[p.teamId], 30.dp)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Body(p.name, weight = FontWeight.SemiBold)
                    Small(listOfNotNull(p.position.ifEmpty { null }, line?.let { "${one(it["MIN"])} min · ${one(it["PTS"])} pts · ${one(it["REB"])} reb · ${one(it["AST"])} ast" }).joinToString(" · "))
                }
                val v = p.sortValue(lg, sort)
                Text(when (sort) {
                    Sort.Points, Sort.Minutes -> one(v)
                    Sort.Impact, Sort.Defense -> signed(v)
                    Sort.Shooting, Sort.Usage -> pct(v, 1)
                    Sort.Youngest -> v?.toInt()?.toString() ?: "–"
                }, color = c.text, fontWeight = FontWeight.SemiBold)
            }
            Divider()
        }
        if (others.isNotEmpty()) {
            item { Text("Other players", color = c.text, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 8.dp)) }
            items(others, key = { "o${it.first}" }) { (id, name) ->
                Body(name, Modifier.fillMaxWidth().clickable { nav.navigate("player/$id") }.padding(vertical = 8.dp))
                Divider()
            }
        }
    }
}
