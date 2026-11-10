package nz.jaredbro.nbastats.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import nz.jaredbro.nbastats.data.Shots
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.sin
import kotlin.math.sqrt

@Composable
fun hexColor(step: Int): Color {
    val c = Theme.colors
    if (step == 0) return c.hexMid
    return lerp(c.hexMid, if (step > 0) c.hot else c.cold, abs(step) / 4f)
}

/** The hexagon heat map on a half court (basket at the bottom), with tap-for-details and a zone table. */
@Composable
fun ShotChartView(chart: Shots.Chart, defence: Boolean = false) {
    val c = Theme.colors
    var picked by remember(chart) { mutableStateOf<Shots.Hex?>(null) }
    val colors = (-4..4).associateWith { hexColor(it) }
    Column {
        Small("${"%,d".format(chart.fga)} shots in ${chart.games} games · ${pct(chart.pct, 1)} FG (${signed((chart.pct - chart.league) * 100)} vs league from the same spots) · " +
            "${pct(chart.efg, 1)} eFG · ${pct(chart.threeShare)} threes", color = c.text2)
        Spacer(Modifier.height(8.dp))
        Canvas(Modifier.fillMaxWidth().aspectRatio(500f / 400f).clip(RoundedCornerShape(10.dp)).pointerInput(chart) {
            detectTapGestures { pos ->
                val k = size.width / 500f
                val x = pos.x / k - 250
                val y = Shots.Y_TOP - pos.y / k
                picked = chart.hexes.minByOrNull { hypot(it.cx - x, it.cy - y) }?.takeIf { hypot(it.cx - x, it.cy - y) <= Shots.HEX_R * 1.1 }
            }
        }) {
            val k = size.width / 500f
            drawRect(c.courtFloor)
            for (h in chart.hexes) {
                drawPath(hexPath(h.cx, h.cy, h.size, k), colors.getValue(h.step))
                if (h == picked) drawPath(hexPath(h.cx, h.cy, h.size, k), c.text, style = Stroke(2f))
            }
            drawCourt(k, c.courtLine)
        }
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Small(if (defence) "Opponents worse " else "Colder ")
            for (s in -4..4) Box(Modifier.size(12.dp).padding(1.dp).background(colors.getValue(s)))
            Small(if (defence) " better" else " hotter than league")
        }
        picked?.let { h ->
            Spacer(Modifier.height(4.dp))
            Small("${h.zone}: ${h.fgm}/${h.fga} (${pct(h.pct, 1)}), league ${pct(h.league, 1)}, ${signed((h.pct - h.league) * 100)} pts", color = c.text)
        }
        Spacer(Modifier.height(8.dp))
        Cells(listOf("Zone", "Shots", "FG%", "League", "±"), listOf(2.4f, 1f, 1f, 1f, 1f), color = c.text2, size = androidx.compose.ui.unit.TextUnit.Unspecified)
        for (z in chart.zones) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(10.dp).background(colors.getValue(z.step)))
                Spacer(Modifier.width(6.dp))
                Box(Modifier.weight(1f)) {
                    Cells(listOf(z.label, pct(z.share), pct(z.pct, 1), pct(z.league, 1), signed(z.diff * 100)), listOf(2.4f, 1f, 1f, 1f, 1f),
                        colors = listOf(null, null, null, null, if (abs(z.diff) > 0.01) (if ((z.diff > 0) != defence) c.positive else c.negative) else null))
                }
            }
        }
    }
}

private fun hexPath(cx: Double, cy: Double, r: Double, k: Float): Path {
    val path = Path()
    for (i in 0 until 6) {
        val a = Math.toRadians(60.0 * i - 30)
        val x = ((cx + r * cos(a)) + 250) * k
        val y = (Shots.Y_TOP - (cy + r * sin(a))) * k
        if (i == 0) path.moveTo(x.toFloat(), y.toFloat()) else path.lineTo(x.toFloat(), y.toFloat())
    }
    path.close()
    return path
}

/** Court lines in NBA coordinates (as shots.court_svg). */
private fun DrawScope.drawCourt(k: Float, color: Color) {
    fun p(x: Double, y: Double) = Offset(((x + 250) * k).toFloat(), ((Shots.Y_TOP - y) * k).toFloat())
    val stroke = 2f
    fun line(x1: Double, y1: Double, x2: Double, y2: Double) = drawLine(color, p(x1, y1), p(x2, y2), stroke)
    line(-250.0, -47.5, 250.0, -47.5)                                   // baseline
    line(-80.0, -47.5, -80.0, 142.5); line(80.0, -47.5, 80.0, 142.5); line(-80.0, 142.5, 80.0, 142.5)  // lane
    line(-60.0, -47.5, -60.0, 142.5); line(60.0, -47.5, 60.0, 142.5)
    line(-30.0, -7.5, 30.0, -7.5)                                        // backboard
    fun arc(cx: Double, cy: Double, r: Double, start: Float, sweep: Float, dashed: Boolean = false) {
        val tl = p(cx - r, cy + r)
        drawArc(color, start, sweep, false, tl, Size((2 * r * k).toFloat(), (2 * r * k).toFloat()),
            style = Stroke(stroke, pathEffect = if (dashed) PathEffect.dashPathEffect(floatArrayOf(12f, 12f)) else null))
    }
    arc(0.0, 142.5, 60.0, 180f, 180f)                                    // free-throw circle, top half
    arc(0.0, 142.5, 60.0, 0f, 180f, dashed = true)
    arc(0.0, 0.0, 40.0, 180f, 180f)                                      // restricted area
    arc(0.0, 0.0, 7.5, 0f, 360f)                                         // rim
    val cornerY = sqrt(237.5 * 237.5 - 220.0 * 220.0)
    line(-220.0, -47.5, -220.0, cornerY); line(220.0, -47.5, 220.0, cornerY)
    val angle = Math.toDegrees(Math.atan2(cornerY, 220.0)).toFloat()
    arc(0.0, 0.0, 237.5, 180f + angle, 180f - 2 * angle)                 // three-point arc
}
