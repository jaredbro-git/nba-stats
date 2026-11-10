package nz.jaredbro.nbastats.ui

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import nz.jaredbro.nbastats.data.Game
import nz.jaredbro.nbastats.data.League
import nz.jaredbro.nbastats.data.Store
import nz.jaredbro.nbastats.data.Team
import java.time.Instant
import java.time.format.DateTimeFormatter
import kotlin.math.abs
import kotlin.math.roundToInt

val PanelShape = RoundedCornerShape(12.dp)

@Composable
fun Panel(title: String?, modifier: Modifier = Modifier, note: String? = null, content: @Composable () -> Unit) {
    val c = Theme.colors
    Column(modifier.fillMaxWidth().clip(PanelShape).background(c.surface).border(1.dp, c.border, PanelShape).padding(16.dp)) {
        if (title != null) {
            Text(title, color = c.text, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
            Spacer(Modifier.height(if (note != null) 4.dp else 10.dp))
        }
        if (note != null) {
            Small(note)
            Spacer(Modifier.height(10.dp))
        }
        content()
    }
}

@Composable
fun Small(text: String, modifier: Modifier = Modifier, color: Color = Theme.colors.muted) =
    Text(text, modifier, color = color, fontSize = 13.sp, lineHeight = 18.sp)

@Composable
fun Body(text: String, modifier: Modifier = Modifier, color: Color = Theme.colors.text, weight: FontWeight? = null) =
    Text(text, modifier, color = color, fontSize = 15.sp, lineHeight = 21.sp, fontWeight = weight)

@Composable
fun Banner(text: String) {
    val c = Theme.colors
    Text(text, Modifier.fillMaxWidth().clip(PanelShape).background(c.accentSoft).padding(12.dp), color = c.text, fontSize = 14.sp, lineHeight = 19.sp)
}

@Composable
fun Loading(text: String = "Loading…") {
    Column(Modifier.fillMaxWidth().padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        CircularProgressIndicator(color = Theme.colors.accent)
        Spacer(Modifier.height(12.dp))
        Small(text)
    }
}

/** A row of choice chips that keeps the selected one scrolled into view. */
@Composable
fun <T> ChipRow(options: List<T>, selected: T, label: (T) -> String, onSelect: (T) -> Unit) {
    val c = Theme.colors
    val state = rememberLazyListState()
    val index = options.indexOf(selected)
    LaunchedEffect(index, options.size) {
        if (index < 0) return@LaunchedEffect
        val info = state.layoutInfo
        val item = info.visibleItemsInfo.firstOrNull { it.index == index }
        when {
            item == null -> state.scrollToItem(index)
            item.offset < info.viewportStartOffset -> state.animateScrollBy((item.offset - info.viewportStartOffset).toFloat())
            item.offset + item.size > info.viewportEndOffset -> state.animateScrollBy((item.offset + item.size - info.viewportEndOffset).toFloat())
        }
    }
    LazyRow(state = state, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items(options.size) { i ->
            FilterChip(
                selected = i == index, onClick = { onSelect(options[i]) }, label = { Text(label(options[i])) },
                colors = FilterChipDefaults.filterChipColors(selectedContainerColor = c.accent, selectedLabelColor = MaterialTheme.colorScheme.onPrimary,
                    labelColor = c.text2, containerColor = c.surface),
            )
        }
    }
}

/** Number tiles, two to a row: (value, label). [tone]: 1 good, -1 bad, 0 plain. */
data class Tile(val value: String, val label: String, val tone: Int = 0, val sub: String? = null)

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun Tiles(tiles: List<Tile>) {
    val c = Theme.colors
    FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp), maxItemsInEachRow = 2) {
        for (t in tiles) {
            Column(Modifier.weight(1f).clip(PanelShape).background(c.surface).border(1.dp, c.border, PanelShape).padding(12.dp)) {
                Small(t.label, color = c.text2)
                Text(t.value, color = toneColor(t.tone), fontWeight = FontWeight.SemiBold, fontSize = 22.sp)
                if (t.sub != null) Small(t.sub)
            }
        }
        if (tiles.size % 2 == 1) Spacer(Modifier.weight(1f))
    }
}

@Composable
fun toneColor(tone: Int): Color = when {
    tone > 0 -> Theme.colors.positive
    tone < 0 -> Theme.colors.negative
    else -> Theme.colors.text
}

/** A team's abbreviation in a coloured circle (the app doesn't download logos, so it works offline). */
@Composable
fun TeamBadge(team: Team?, size: Dp = 30.dp) {
    val color = teamColor(team?.abbr ?: "")
    Box(Modifier.size(size).clip(CircleShape).background(color), contentAlignment = Alignment.Center) {
        Text(team?.abbr ?: "?", color = Color.White, fontWeight = FontWeight.Bold, fontSize = (size.value * 0.32).sp, maxLines = 1)
    }
}

private val TEAM_COLORS = mapOf(
    "ATL" to 0xFFC8102E, "BOS" to 0xFF007A33, "BKN" to 0xFF333333, "CHA" to 0xFF1D1160, "CHI" to 0xFFCE1141, "CLE" to 0xFF860038,
    "DAL" to 0xFF00538C, "DEN" to 0xFF0E2240, "DET" to 0xFFC8102E, "GSW" to 0xFF1D428A, "HOU" to 0xFFCE1141, "IND" to 0xFF002D62,
    "LAC" to 0xFFC8102E, "LAL" to 0xFF552583, "MEM" to 0xFF5D76A9, "MIA" to 0xFF98002E, "MIL" to 0xFF00471B, "MIN" to 0xFF0C2340,
    "NOP" to 0xFF0C2340, "NYK" to 0xFF006BB6, "OKC" to 0xFF007AC1, "ORL" to 0xFF0077C0, "PHI" to 0xFF006BB6, "PHX" to 0xFF1D1160,
    "POR" to 0xFFE03A3E, "SAC" to 0xFF5A2D81, "SAS" to 0xFF6B7378, "TOR" to 0xFFCE1141, "UTA" to 0xFF002B5C, "WAS" to 0xFF002B5C,
)

fun teamColor(abbr: String) = Color(TEAM_COLORS[abbr] ?: 0xFF555555)

/** Two-part bar for a win chance: away share on the left, home on the right. */
@Composable
fun WinBar(awayWin: Double, modifier: Modifier = Modifier) {
    val c = Theme.colors
    Row(modifier.fillMaxWidth().height(12.dp)) {
        val a = awayWin.coerceIn(0.01, 0.99).toFloat()
        Box(Modifier.weight(a).fillMaxSize().clip(RoundedCornerShape(topStart = 4.dp, bottomStart = 4.dp)).background(c.series1))
        Spacer(Modifier.width(2.dp))
        Box(Modifier.weight(1 - a).fillMaxSize().clip(RoundedCornerShape(topEnd = 4.dp, bottomEnd = 4.dp)).background(c.series2))
    }
}

/** A row of label + right-aligned values, for small tables. */
@Composable
fun Cells(cells: List<String>, weights: List<Float>, bold: Boolean = false, color: Color = Theme.colors.text, size: TextUnit = 14.sp,
          colors: List<Color?>? = null, onClick: (() -> Unit)? = null) {
    Row(Modifier.fillMaxWidth().let { if (onClick != null) it.clickable(onClick = onClick) else it }.padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically) {
        cells.forEachIndexed { i, text ->
            Text(text, Modifier.weight(weights[i]), color = colors?.getOrNull(i) ?: color, fontSize = size,
                fontWeight = if (bold) FontWeight.SemiBold else null, textAlign = if (i == 0) TextAlign.Start else TextAlign.End,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

@Composable
fun Divider() = Box(Modifier.fillMaxWidth().height(1.dp).background(Theme.colors.grid))

// --- Formatting ----------------------------------------------------------------------------------------

fun pct(v: Double?, digits: Int = 0): String = if (v == null) "–" else "%.${digits}f%%".format(v * 100)
fun one(v: Double?): String = if (v == null) "–" else "%.1f".format(v)
fun signed(v: Double?, digits: Int = 1): String {
    if (v == null) return "–"
    val text = "%.${digits}f".format(abs(v))
    return if (text.toDouble() == 0.0) text else (if (v > 0) "+" else "−") + text
}
fun whole(v: Double): String = v.roundToInt().toString()

private val DAY_FMT = DateTimeFormatter.ofPattern("EEE d MMM")
private val TIME_FMT = DateTimeFormatter.ofPattern("h:mm a")
fun nzDay(i: Instant?): String = i?.atZone(Store.TZ)?.format(DAY_FMT) ?: "TBD"
fun nzTime(i: Instant?): String = i?.atZone(Store.TZ)?.format(TIME_FMT)?.lowercase() ?: ""

fun height(inches: Double?): String = if (inches == null || inches == 0.0) "–" else "${(inches / 12).toInt()}′${(inches % 12).roundToInt()}″"

// --- Loading the league off the main thread ---------------------------------------------------------------

/** Why the bundle couldn't be opened (e.g. it came from an older Mac app); shown instead of the pages. */
var leagueError by mutableStateOf<String?>(null)

@Composable
fun rememberLeague(): League? {
    val context: Context = LocalContext.current
    val generation = Store.generation
    val lg by produceState(Store.loaded(), generation) {
        value = withContext(Dispatchers.Default) {
            if (!Store.exists(context)) null
            else runCatching { Store.league(context) }.onSuccess { leagueError = null }
                .onFailure { leagueError = it.message ?: "Couldn't open the data from your Mac." }.getOrNull()
        }
    }
    return lg
}

/** The game's score and status: live from stats.nba.com when the phone has it, else from the bundle. */
fun Game.now(): Triple<Int, Int, Int> {
    val live = LiveScores.scores[id]
    return if (live != null) Triple(live.status, live.awayScore, live.homeScore) else Triple(status, awayScore, homeScore)
}

fun Game.statusText(): String = LiveScores.scores[id]?.statusText ?: statusText
