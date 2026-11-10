package nz.jaredbro.nbastats.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

/** The Mac app's colour tokens (app/static/style.css), light and dark. */
data class AppColors(
    val page: Color, val surface: Color, val text: Color, val text2: Color, val muted: Color, val grid: Color,
    val border: Color, val accent: Color, val accentSoft: Color, val positive: Color, val negative: Color,
    val warning: Color, val series1: Color, val series2: Color, val cold: Color, val hot: Color, val hexMid: Color,
    val courtFloor: Color, val courtLine: Color,
)

private val Light = AppColors(
    page = Color(0xFFF9F9F7), surface = Color(0xFFFCFCFB), text = Color(0xFF0B0B0B), text2 = Color(0xFF52514E),
    muted = Color(0xFF898781), grid = Color(0xFFE1E0D9), border = Color(0x1A0B0B0B), accent = Color(0xFF2A78D6),
    accentSoft = Color(0x1F2A78D6), positive = Color(0xFF006300), negative = Color(0xFFC4302B), warning = Color(0xFFA86200),
    series1 = Color(0xFF2A78D6), series2 = Color(0xFFEB6834), cold = Color(0xFF2A78D6), hot = Color(0xFFE34948),
    hexMid = Color(0xFFD6D5CE), courtFloor = Color(0xFFF4F3EE), courtLine = Color(0xFFA9A89E),
)
private val Dark = AppColors(
    page = Color(0xFF0D0D0D), surface = Color(0xFF1A1A19), text = Color(0xFFF0EFEC), text2 = Color(0xFFC3C2B7),
    muted = Color(0xFF898781), grid = Color(0xFF2C2C2A), border = Color(0x1AFFFFFF), accent = Color(0xFF3987E5),
    accentSoft = Color(0x243987E5), positive = Color(0xFF0CA30C), negative = Color(0xFFF07167), warning = Color(0xFFE3A33B),
    series1 = Color(0xFF3987E5), series2 = Color(0xFFD95926), cold = Color(0xFF3987E5), hot = Color(0xFFE66767),
    hexMid = Color(0xFF4A4A46), courtFloor = Color(0xFF141413), courtLine = Color(0xFF5C5B56),
)

val LocalColors = staticCompositionLocalOf { Dark }

object Theme {
    val colors: AppColors @Composable get() = LocalColors.current
}

@Composable
fun AppTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val c = if (dark) Dark else Light
    val scheme = (if (dark) darkColorScheme() else lightColorScheme()).copy(
        primary = c.accent, onPrimary = Color.White, background = c.page, onBackground = c.text,
        surface = c.surface, onSurface = c.text, surfaceVariant = c.grid, onSurfaceVariant = c.text2,
        outline = c.border, secondaryContainer = c.accentSoft, onSecondaryContainer = c.text,
    )
    CompositionLocalProvider(LocalColors provides c) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
