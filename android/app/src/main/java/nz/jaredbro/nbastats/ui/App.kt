package nz.jaredbro.nbastats.ui

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.materialIcon
import androidx.compose.material.icons.materialPath
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import kotlinx.coroutines.delay
import nz.jaredbro.nbastats.data.MacLink
import nz.jaredbro.nbastats.data.Nba
import nz.jaredbro.nbastats.data.Store
import java.time.Instant

/** Near-live scores from stats.nba.com's schedule, refreshed every minute while a game is on. */
object LiveScores {
    var scores by mutableStateOf<Map<String, Nba.Live>>(emptyMap())
    var updated by mutableStateOf<Instant?>(null)
    var error by mutableStateOf<String?>(null)

    suspend fun refresh(context: Context, season: String, ttl: Long) {
        try {
            scores = Nba.scores(context, season, ttl)
            updated = Instant.now()
            error = null
        } catch (e: Exception) {
            error = e.message
        }
    }

    val anyLive get() = scores.values.any { it.status == 2 }
}

private val ROOTS = setOf("teams", "players", "predictions", "season", "trades")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun App() {
    val c = Theme.colors
    val context = LocalContext.current
    val nav = rememberNavController()
    val entry by nav.currentBackStackEntryAsState()
    val route = entry?.destination?.route ?: "teams"
    val lg = rememberLeague()

    // A fresh copy from the Mac when the last one is 30+ minutes old (home Wi-Fi only; quietly skipped elsewhere).
    LaunchedEffect(Unit) {
        while (true) {
            if (MacLink.pairedMac(context) != null && System.currentTimeMillis() - MacLink.lastCopy(context) > MacLink.COPY_EVERY_MS) {
                MacLink.sync(context)
            }
            delay(MacLink.COPY_EVERY_MS)
        }
    }
    // Scores: every minute while a game is on, every 10 minutes otherwise.
    LaunchedEffect(lg?.cur) {
        val season = lg?.cur ?: return@LaunchedEffect
        while (true) {
            val live = LiveScores.anyLive
            LiveScores.refresh(context, season, if (live) 50_000 else 9 * Nba.MINUTE)
            delay(if (LiveScores.anyLive) 60_000 else 10 * Nba.MINUTE)
        }
    }

    Scaffold(
        containerColor = c.page,
        topBar = {
            TopAppBar(
                title = { Text(titleFor(route), fontWeight = FontWeight.SemiBold) },
                navigationIcon = {
                    if (route !in ROOTS) IconButton({ nav.popBackStack() }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
                },
                actions = { IconButton({ nav.navigate("sync") { launchSingleTop = true } }) { Icon(Icons.Filled.Refresh, "Sync with your Mac") } },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = c.page, titleContentColor = c.text,
                    navigationIconContentColor = c.text, actionIconContentColor = c.text2),
            )
        },
        bottomBar = {
            NavigationBar(containerColor = c.surface) {
                for ((r, label, icon) in TABS) {
                    val selected = sectionOf(route) == r
                    NavigationBarItem(selected = selected, onClick = {
                        nav.navigate(r) { popUpTo("teams") { saveState = true }; launchSingleTop = true; restoreState = true }
                    }, icon = { Icon(icon, label) }, label = { Text(label) },
                        colors = NavigationBarItemDefaults.colors(selectedIconColor = c.accent, selectedTextColor = c.text,
                            indicatorColor = c.accentSoft, unselectedIconColor = c.text2, unselectedTextColor = c.text2))
                }
            }
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize().background(c.page)) {
            MacLink.status?.let { Text(it, Modifier.fillMaxWidth().background(c.accentSoft).padding(horizontal = 16.dp, vertical = 8.dp), color = c.text, fontSize = 13.sp) }
            if ((!Store.exists(context) || leagueError != null) && route != "sync" && Store.generation >= 0) {
                leagueError?.let { Banner(it) }
                SyncScreen()
                return@Column
            }
            NavHost(nav, startDestination = "teams") {
                composable("teams") { TeamsScreen(nav) }
                composable("team/{abbr}") { TeamScreen(nav, it.arguments?.getString("abbr") ?: "") }
                composable("game/{id}") { GameScreen(nav, it.arguments?.getString("id") ?: "") }
                composable("players") { PlayersScreen(nav) }
                composable("player/{id}", arguments = listOf(navArgument("id") { type = NavType.LongType })) {
                    PlayerScreen(nav, it.arguments?.getLong("id") ?: 0L)
                }
                composable("predictions") { PredictionsScreen(nav) }
                composable("season") { SimulatorScreen(nav) }
                composable("trades") { TradesScreen(nav) }
                composable("sync") { SyncScreen() }
            }
        }
    }
}

/** Two arrows pointing opposite ways (Material's swap_horiz, which isn't in the core icon set). */
private val SwapIcon = materialIcon("SwapHoriz") {
    materialPath {
        moveTo(6.99f, 11f); lineTo(3f, 15f); lineToRelative(3.99f, 4f); verticalLineToRelative(-3f)
        horizontalLineTo(14f); verticalLineToRelative(-2f); horizontalLineTo(6.99f); verticalLineToRelative(-3f); close()
        moveTo(21f, 9f); lineToRelative(-3.99f, -4f); verticalLineToRelative(3f); horizontalLineTo(10f)
        verticalLineToRelative(2f); horizontalLineToRelative(7.01f); verticalLineToRelative(3f); lineTo(21f, 9f); close()
    }
}

private val TABS = listOf(
    Triple("teams", "Teams", Icons.Filled.Home), Triple("players", "Players", Icons.Filled.Person),
    Triple("predictions", "Tracker", Icons.Filled.CheckCircle), Triple("season", "Season", Icons.Filled.DateRange),
    Triple("trades", "Trades", SwapIcon),
)

/** Which bottom tab a page belongs to: the tab pages themselves, players under Players, games and teams under Teams. */
private fun sectionOf(route: String) = when {
    route in ROOTS -> route
    route.startsWith("player") -> "players"
    else -> "teams"
}

private fun titleFor(route: String) = when {
    route == "teams" -> "NBA"
    route.startsWith("team/") -> "Team"
    route.startsWith("game/") -> "Game"
    route == "players" -> "Players"
    route.startsWith("player/") -> "Player"
    route == "predictions" -> "Prediction tracker"
    route == "season" -> "Season simulator"
    route == "trades" -> "Trade machine"
    route == "sync" -> "Sync with your Mac"
    else -> "NBA"
}
