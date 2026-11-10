package nz.jaredbro.nbastats

import nz.jaredbro.nbastats.data.League
import nz.jaredbro.nbastats.data.Simulator
import nz.jaredbro.nbastats.data.Query
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.sql.DriverManager
import java.time.LocalDate

/**
 * The phone's model must give the Mac's answers. Build a bundle and the expected answers with
 *   python -m app.bundle /tmp/bundle.db /tmp/expected.json
 * then run NBA_BUNDLE=/tmp/bundle.db NBA_EXPECTED=/tmp/expected.json ./gradlew testReleaseUnitTest
 */
class ParityTest {
    private fun league(): Pair<League, JSONObject>? {
        val bundle = System.getProperty("nba.bundle").orEmpty()
        val expected = System.getProperty("nba.expected").orEmpty()
        if (bundle.isEmpty() || !File(bundle).exists() || !File(expected).exists()) return null
        val conn = DriverManager.getConnection("jdbc:sqlite:$bundle")
        val q = Query { sql, args ->
            conn.prepareStatement(sql).use { st ->
                args.forEachIndexed { i, a -> st.setObject(i + 1, a) }
                st.executeQuery().use { rs ->
                    val cols = (1..rs.metaData.columnCount).map { rs.metaData.getColumnLabel(it) }
                    buildList { while (rs.next()) add(cols.associateWith { rs.getObject(it) }) }
                }
            }
        }
        return League(q) to JSONObject(File(expected).readText())
    }

    private val tol = 1e-6

    @Test
    fun predictionsMatchPython() {
        val (lg, exp) = league() ?: return assumeTrue("No bundle given", false)
        val cases = exp.getJSONArray("cases")
        assumeTrue(cases.length() > 0)
        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i)
            val outArr = c.getJSONArray("out")
            val out = (0 until outArr.length()).map { outArr.getLong(it) }.toSet()
            val p = lg.predict(c.getLong("home"), c.getLong("away"), out, LocalDate.parse(c.getString("us_date")),
                c.getBoolean("neutral"), withMatchups = true)
            val id = c.getString("game_id")
            assertEquals("$id home pts", c.getDouble("home_pts"), p.home.pts, tol)
            assertEquals("$id away pts", c.getDouble("away_pts"), p.away.pts, tol)
            assertEquals("$id home win", c.getDouble("home_win"), p.homeWin, tol)
            val lines = c.getJSONArray("home_lines")
            assertEquals("$id line count", lines.length(), p.home.lines.size)
            for (j in 0 until lines.length()) {
                val e = lines.getJSONObject(j)
                val l = p.home.lines[j]
                assertEquals("$id line $j player", e.getLong("id"), l.player.id)
                assertEquals("$id ${l.player.name} MIN", e.getDouble("MIN"), l.min, tol)
                for (k in listOf("PTS", "REB", "AST")) assertEquals("$id ${l.player.name} $k", e.getDouble(k), l[k], tol)
            }
            val likely = c.getJSONObject("likely")
            val rows = p.matchups.values.flatMap { it.first }
            for (r in rows) {
                val want = likely.opt(r.shooter.id.toString())
                assertEquals("$id likely defender of ${r.shooter.name}", if (want == null || want == JSONObject.NULL) null else (want as Number).toLong(), r.likely)
            }
        }
    }

    @Test
    fun matchupChangeAndEstimatesMatchPython() {
        val (lg, exp) = league() ?: return assumeTrue("No bundle given", false)
        val mc = exp.getJSONObject("matchup_change")
        val p = lg.predict(mc.getLong("home"), mc.getLong("away"), emptySet(), null, false, mapOf(mc.getLong("shooter") to mc.getLong("defender")))
        assertEquals("matchup change home pts", mc.getDouble("home_pts"), p.home.pts, tol)
        assertEquals("matchup change away pts", mc.getDouble("away_pts"), p.away.pts, tol)
        val ests = exp.getJSONArray("estimates")
        for (i in 0 until ests.length()) {
            val e = ests.getJSONObject(i)
            val got = lg.matchups.estimate(e.getLong("shooter"), e.getLong("defender"))!!
            assertEquals("estimate $i pts100", e.getDouble("pts100"), got.pts100, tol)
            assertEquals("estimate $i fg", e.getDouble("fg"), got.fg, tol)
            assertEquals("estimate $i fg3", e.getDouble("fg3"), got.fg3, tol)
            assertEquals("estimate $i effect100", e.getDouble("effect100"), got.effect100, tol)
        }
    }

    @Test
    fun simulatorMatchesPython() {
        val (lg, expected) = league() ?: return
        val sims = expected.optJSONArray("sims") ?: return
        for (i in 0 until sims.length()) {
            val e = sims.getJSONObject(i)
            val m = e.getJSONObject("missing")
            val missing = m.keys().asSequence().associate { it.toLong() to (if (m.isNull(it)) null else m.getInt(it)) }
            val got = Simulator.run(lg, missing)
            assertEquals("sim $i team sd", e.getDouble("team_sd"), got.teamSd, 1e-9)
            assertEquals("sim $i games left", e.getInt("games_left"), got.gamesLeft)
            // Different random draws: compare within the noise of 10,000 seasons (about 0.15 wins, 0.7 points of odds).
            val teams = e.getJSONObject("teams")
            for (t in got.teams) {
                val x = teams.getJSONObject(t.team.id.toString())
                assertEquals("sim $i ${t.team.abbr} wins", x.getDouble("wins"), t.wins, 0.6)
                assertEquals("sim $i ${t.team.abbr} losses", x.getDouble("losses"), t.losses, 0.6)
                assertEquals("sim $i ${t.team.abbr} playoffs", x.getDouble("playoffs"), t.playoffs, 0.03)
                assertEquals("sim $i ${t.team.abbr} title", x.getDouble("title"), t.title, 0.03)
                assertEquals("sim $i ${t.team.abbr} #1 seed", x.getDouble("seed1"), t.seed1, 0.03)
            }
        }
    }

    @Test
    fun seriesWinMatchesPython() {
        // simulator.series_win's values.
        assertEquals(0.5, Simulator.seriesWin(0.5, 0.5), 1e-12)
        assertEquals(0.710208, Simulator.seriesWin(0.6, 0.6), 1e-12)
        assertEquals(0.70263025, Simulator.seriesWin(0.7, 0.45), 1e-12)
        assertEquals(0.075804, Simulator.seriesWin(0.3, 0.2), 1e-12)
    }

    @Test
    fun quickMarginMatchesPredict() {
        val (lg, expected) = league() ?: return
        val cases = expected.getJSONArray("cases")
        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i)
            val out = (0 until c.getJSONArray("out").length()).map { c.getJSONArray("out").getLong(it) }.toSet()
            val date = java.time.LocalDate.parse(c.getString("us_date"))
            val p = lg.predict(c.getLong("home"), c.getLong("away"), out, date, c.getBoolean("neutral"))
            assertEquals("case $i quick margin", p.margin, lg.quickMargin(c.getLong("home"), c.getLong("away"), out, date, c.getBoolean("neutral")), 1e-9)
        }
    }

    @Test
    fun erfMatchesPython() {
        // Values of Python's math.erf.
        assertEquals(0.0, League.erf(0.0), 1e-15)
        assertEquals(0.5204998778130465, League.erf(0.5), 1e-13)
        assertEquals(-0.8427007929497149, League.erf(-1.0), 1e-13)
        assertEquals(0.9953222650189527, League.erf(2.0), 1e-13)
        assertEquals(0.9999779095030014, League.erf(3.0), 1e-13)
        assertEquals(0.9999999845827421, League.erf(4.0), 1e-13)
    }
}
