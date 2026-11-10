// Checks the iPhone app's model against the Mac's Python model. Build a bundle and Python's answers with
//   python -m app.bundle /tmp/b.db /tmp/e.json
// then run ios/Tools/parity.sh /tmp/b.db /tmp/e.json (compiles this with the app's model files and runs it).
import Foundation

let args = CommandLine.arguments
guard args.count == 3, let db = Db(path: args[1]),
      let expected = (try? JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: args[2])))) as? [String: Any] else {
    print("usage: parity <bundle.db> <expected.json>"); exit(2)
}
let lg = try League(db: db)
let tol = 1e-6
var failures = 0, checks = 0

func check(_ label: String, _ want: Double?, _ got: Double?, _ tolerance: Double = tol) {
    checks += 1
    guard let want, let got, abs(want - got) <= tolerance else {
        failures += 1
        if failures <= 25 { print("FAIL \(label): want \(want.map { "\($0)" } ?? "nil"), got \(got.map { "\($0)" } ?? "nil")") }
        return
    }
}
func int(_ v: Any?) -> Int? { Json.double(v).map { Int($0) } }

// Predictions, player lines and likely defenders.
for c in expected["cases"] as? [[String: Any]] ?? [] {
    let id = c["game_id"] as? String ?? "?"
    let out = Set((c["out"] as? [Any] ?? []).compactMap(int))
    let p = lg.predict(home: int(c["home"])!, away: int(c["away"])!, out: out, usDate: c["us_date"] as? String,
                       neutral: c["neutral"] as? Bool ?? false, withMatchups: true)
    check("\(id) home pts", Json.double(c["home_pts"]), p.home.pts)
    check("\(id) away pts", Json.double(c["away_pts"]), p.away.pts)
    check("\(id) home win", Json.double(c["home_win"]), p.homeWin)
    let lines = c["home_lines"] as? [[String: Any]] ?? []
    check("\(id) line count", Double(lines.count), Double(p.home.lines.count))
    for (j, e) in lines.enumerated() where j < p.home.lines.count {
        let l = p.home.lines[j]
        check("\(id) line \(j) player", Json.double(e["id"]), Double(l.player.id))
        check("\(id) \(l.player.name) MIN", Json.double(e["MIN"]), l.min)
        for k in ["PTS", "REB", "AST"] { check("\(id) \(l.player.name) \(k)", Json.double(e[k]), l[k]) }
    }
    let likely = c["likely"] as? [String: Any] ?? [:]
    for r in p.matchups.values.flatMap(\.rows) {
        let want = int(likely["\(r.shooter.id)"])
        check("\(id) likely defender of \(r.shooter.name)", Double(want ?? -1), Double(r.likely ?? -1))
    }
    // quick_margin must equal predict's margin.
    let q = lg.quickMargin(home: int(c["home"])!, away: int(c["away"])!, out: out, usDate: c["us_date"] as? String, neutral: c["neutral"] as? Bool ?? false)
    let plain = lg.predict(home: int(c["home"])!, away: int(c["away"])!, out: out, usDate: c["us_date"] as? String, neutral: c["neutral"] as? Bool ?? false)
    check("\(id) quick margin", plain.margin, q, 1e-9)
}

// A matchup change, and matchup estimates.
if let mc = expected["matchup_change"] as? [String: Any], let s = int(mc["shooter"]), let d = int(mc["defender"]) {
    let p = lg.predict(home: int(mc["home"])!, away: int(mc["away"])!, out: [], overrides: [s: d])
    check("matchup change home pts", Json.double(mc["home_pts"]), p.home.pts)
    check("matchup change away pts", Json.double(mc["away_pts"]), p.away.pts)
}
for (i, e) in (expected["estimates"] as? [[String: Any]] ?? []).enumerated() {
    let got = lg.matchups.estimate(int(e["shooter"])!, int(e["defender"])!)
    for k in ["pts100", "fg", "fg3", "effect100"] {
        let v: Double? = got.map { k == "pts100" ? $0.pts100 : k == "fg" ? $0.fg : k == "fg3" ? $0.fg3 : $0.effect100 }
        check("estimate \(i) \(k)", Json.double(e[k]), v)
    }
}

// Series odds, exactly as simulator.series_win.
check("series 0.5/0.5", 0.5, Simulator.seriesWin(0.5, 0.5), 1e-12)
check("series 0.6/0.6", 0.710208, Simulator.seriesWin(0.6, 0.6), 1e-12)
check("series 0.7/0.45", 0.70263025, Simulator.seriesWin(0.7, 0.45), 1e-12)
check("series 0.3/0.2", 0.075804, Simulator.seriesWin(0.3, 0.2), 1e-12)

// The season simulator: different random draws, so within the noise of 10,000 seasons.
for (i, e) in (expected["sims"] as? [[String: Any]] ?? []).enumerated() {
    var missing: [Int: Int?] = [:]
    for (k, v) in e["missing"] as? [String: Any] ?? [:] { missing[Int(k)!] = int(v) }
    let start = Date()
    let got = Simulator.run(lg, missing: missing)
    print(String(format: "sim %d: %.2f s", i, Date().timeIntervalSince(start)))
    check("sim \(i) team sd", Json.double(e["team_sd"]), got.teamSd, 1e-9)
    check("sim \(i) games left", Json.double(e["games_left"]), Double(got.gamesLeft))
    let teams = e["teams"] as? [String: [String: Any]] ?? [:]
    for t in got.teams {
        let x = teams["\(t.team.id)"] ?? [:]
        check("sim \(i) \(t.team.abbr) wins", Json.double(x["wins"]), t.wins, 0.6)
        check("sim \(i) \(t.team.abbr) losses", Json.double(x["losses"]), t.losses, 0.6)
        check("sim \(i) \(t.team.abbr) playoffs", Json.double(x["playoffs"]), t.playoffs, 0.03)
        check("sim \(i) \(t.team.abbr) title", Json.double(x["title"]), t.title, 0.03)
        check("sim \(i) \(t.team.abbr) #1 seed", Json.double(x["seed1"]), t.seed1, 0.03)
    }
}

// Ratings redone on the phone (Ratings.swift) from the bundle's own game logs must give the Mac's numbers.
if let redo = try? League(db: db), redo.redoRatings(force: true) {
    for (tid, t) in lg.teams.sorted(by: { $0.key < $1.key }) {
        let a = lg.teamParts(tid), b = redo.teamParts(tid)
        check("ratings \(t.abbr) off", a?.off, b?.off, 1e-9); check("ratings \(t.abbr) def", a?.def, b?.def, 1e-9)
        check("ratings \(t.abbr) pace", a?.pace, b?.pace, 1e-9); check("ratings \(t.abbr) weight", a?.curWeight, b?.curWeight, 1e-12)
        check("ratings \(t.abbr) adj off", a?.adjOff, b?.adjOff, 1e-9); check("ratings \(t.abbr) adj def", a?.adjDef, b?.adjDef, 1e-9)
        for s in [lg.cur, lg.prev] {
            let x = lg.seasons[s]?[tid], y = redo.seasons[s]?[tid]
            check("ratings \(t.abbr) \(s) gp", x.map { Double($0.gp) }, y.map { Double($0.gp) }, 0)
            check("ratings \(t.abbr) \(s) wins", x.map { Double($0.w) }, y.map { Double($0.w) }, 0)
            check("ratings \(t.abbr) \(s) ortg", x?.ortg, y?.ortg, 1e-9); check("ratings \(t.abbr) \(s) pace", x?.pace, y?.pace, 1e-9)
            check("ratings \(t.abbr) \(s) last 10 net", x?.l10net, y?.l10net, 1e-9)
        }
    }
    check("ratings offset off", lg.offsets.0, redo.offsets.0, 1e-9); check("ratings offset def", lg.offsets.1, redo.offsets.1, 1e-9)
    check("ratings league ortg", lg.leagueOrtg, redo.leagueOrtg, 1e-9); check("ratings league pace", lg.leaguePace, redo.leaguePace, 1e-9)
    check("ratings home court", lg.homeAdv, redo.homeAdv, 1e-9)
    for pid in lg.playerOrder {
        let a = lg.players[pid]!, b = redo.players[pid]!
        check("ratings \(a.name) mpg", a.mpg, b.mpg, 1e-9)
        for k in League.stats { check("ratings \(a.name) \(k) rate", a.rates[k], b.rates[k], 1e-9) }
    }
    for c in expected["cases"] as? [[String: Any]] ?? [] {
        let out = Set((c["out"] as? [Any] ?? []).compactMap(int))
        let p = redo.predict(home: int(c["home"])!, away: int(c["away"])!, out: out, usDate: c["us_date"] as? String, neutral: c["neutral"] as? Bool ?? false)
        check("ratings \(c["game_id"] ?? "?") home win", Json.double(c["home_win"]), p.homeWin)
    }
} else {
    failures += 1; print("FAIL ratings: the bundle has no rating_params")
}

// Results the phone downloads itself (LeagueGameLog, as the Mac caches it) must become the same rows as the bundle's.
if let cache = ProcessInfo.processInfo.environment["NBA_CACHE"] {
    func rows(_ kind: String) -> [[String: Any]] {
        let url = URL(fileURLWithPath: "\(cache)/gamelog_\(kind)_\(lg.cur).json")
        guard let f = ((try? JSONSerialization.jsonObject(with: Data(contentsOf: url))) as? [[String: Any]])?.first,
              let cols = f["columns"] as? [String], let data = f["data"] as? [[Any]] else { return [] }
        return data.map { Dictionary(uniqueKeysWithValues: zip(cols, $0)) }
    }
    let bundleTeam = Ratings.teamRows(db).filter { $0.season == lg.cur }, bundlePlayer = Ratings.playerRows(db).filter { $0.season == lg.cur }
    let lastDays = Set(bundleTeam.map(\.date)).sorted().suffix(3)
    let known = Set(bundleTeam.filter { !lastDays.contains($0.date) }.map(\.gameId))
    let got = Ratings.fromGameLogs(season: lg.cur, team: rows("T"), player: rows("P"), known: known)
    let want = Dictionary(uniqueKeysWithValues: bundleTeam.filter { lastDays.contains($0.date) }.map { ("\($0.gameId)-\($0.teamId)", $0) })
    check("downloaded team rows", Double(want.count), Double(got.team.count), 0)
    for r in got.team {
        let w = want["\(r.gameId)-\(r.teamId)"]
        check("downloaded \(r.gameId) \(r.teamId) poss", w?.poss, r.poss, 1e-9); check("downloaded \(r.gameId) \(r.teamId) min", w?.min, r.min, 0)
        check("downloaded \(r.gameId) \(r.teamId) pts", w?.pts, r.pts, 0); check("downloaded \(r.gameId) \(r.teamId) opp pts", w?.oppPts, r.oppPts, 0)
        check("downloaded \(r.gameId) \(r.teamId) home", w.map { $0.home ? 1 : 0 }, r.home ? 1 : 0, 0)
        check("downloaded \(r.gameId) \(r.teamId) opp", w.map { Double($0.oppId) }, Double(r.oppId), 0)
        check("downloaded \(r.gameId) \(r.teamId) date", w?.date == r.date ? 1 : 0, 1, 0)
    }
    let wantP = Dictionary(uniqueKeysWithValues: bundlePlayer.filter { lastDays.contains($0.date) }.map { ("\($0.gameId)-\($0.playerId)", $0) })
    check("downloaded player rows", Double(wantP.count), Double(got.player.count), 0)
    for r in got.player {
        let w = wantP["\(r.gameId)-\(r.playerId)"]
        check("downloaded \(r.name) min", w?.min, r.min, 1e-9)
        for k in League.stats { check("downloaded \(r.name) \(k)", w?.stats[k], r.stats[k], 0) }
    }
}

print(failures == 0 ? "PASS: \(checks) checks match Python" : "FAILED \(failures) of \(checks) checks")
exit(failures == 0 ? 0 : 1)
