package nz.jaredbro.nbastats.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import nz.jaredbro.nbastats.data.League
import kotlin.math.roundToInt

/** The expected outcome of one player guarding another (the Mac app's matchup popup). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EstimateSheet(lg: League, shooter: Long, defender: Long, onDismiss: () -> Unit, onPlayer: (Long) -> Unit) {
    val c = Theme.colors
    val s = lg.players[shooter]
    val d = lg.players[defender]
    val est = remember(lg, shooter, defender) { lg.matchups.estimate(shooter, defender) }
    val pair = remember(lg, shooter, defender) { lg.matchups.pair(shooter, defender) }
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = c.surface) {
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 32.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(s?.name ?: "$shooter", color = c.text, fontWeight = FontWeight.Bold, fontSize = 19.sp, modifier = Modifier.clickable { onPlayer(shooter) })
            Small("guarded by", color = c.text2)
            Text(d?.name ?: "$defender", color = c.text, fontWeight = FontWeight.Bold, fontSize = 19.sp, modifier = Modifier.clickable { onPlayer(defender) })
            Small("${height(s?.height)} ${s?.position ?: ""}  vs  ${height(d?.height)} ${d?.position ?: ""}")
            if (est == null) { Small("Not enough tracked possessions for ${s?.name} to estimate a matchup."); return@Column }
            if (pair == null) Banner("This matchup has never happened (tracked since ${lg.matchups.firstSeason}). The expected outcome is estimated from each player's numbers.")
            Tiles(listOf(
                Tile(one(est.pts100), "Points per 100 possessions", if (est.effect100 < -0.5) 1 else if (est.effect100 > 0.5) -1 else 0,
                    "${signed(est.effect100)} vs his usual ${one(est.basePts100)}"),
                Tile(pct(est.fg, 1), "FG%", sub = "usually ${pct(est.baseFg, 1)}"),
                Tile(pct(est.fg3, 1), "3P%", sub = "usually ${pct(est.baseFg3, 1)}"),
            ))
            val mpg = s?.mpg?.takeIf { it > 0 } ?: 30.0
            val guarded = lg.matchups.primaryShare * mpg / 48 * lg.leaguePace
            val g = guarded / 100
            Body("In a game where ${d?.name} is his main defender (about ${(lg.matchups.primaryShare * 100).roundToInt()}% of his possessions, ~${whole(guarded)} possessions): " +
                "${one(est.pts100 * g)} pts on ${one(est.fga100 * g * est.fg)}/${one(est.fga100 * g)} FG, ${one(est.fg3a100 * g * est.fg3)}/${one(est.fg3a100 * g)} 3P.")
            if (pair != null) {
                Spacer(Modifier.height(4.dp))
                Text("Head to head", color = c.text, fontWeight = FontWeight.SemiBold)
                Small("${pair.fgm}/${pair.fga} FG, ${pair.fg3m}/${pair.fg3a} 3P, ${pair.pts} pts on ${whole(pair.poss)} possessions in ${pair.gp} games " +
                    "(${if (pair.poss > 0) whole(100 * pair.pts / pair.poss) else "–"} per 100). ${est.confidence} confidence.", color = c.text)
            }
            Spacer(Modifier.height(4.dp))
            Text("How it's estimated", color = c.text, fontWeight = FontWeight.SemiBold)
            Cells(listOf("His usual scoring", "${one(est.basePts100)} per 100"), listOf(2f, 1f))
            Cells(listOf("${d?.name}'s defensive rating", signed(est.rating100)), listOf(2f, 1f),
                colors = listOf(null, if (est.rating100 < -0.5) c.positive else if (est.rating100 > 0.5) c.negative else null))
            est.closeFg?.let { Small("Shooters hit ${signed(it * 100)} FG% points vs normal with him closest${est.closeFg3?.let { t -> " (${signed(t * 100)} on threes)" } ?: ""}.") }
            Cells(listOf("Height difference", est.size?.let { "${signed(it, 0)}″" } ?: "–"), listOf(2f, 1f))
            Small("Height barely matters once the defender's own ability is counted.")
            Cells(listOf("Head to head", est.h2h100?.let { signed(it) } ?: "–"), listOf(2f, 1f))
            Small(if (est.h2h100 != null) "Counted at ${(est.h2hWeight * 100).roundToInt()}% weight, more as their history grows." else "None: the estimate uses the rating and height only.")
        }
    }
}
