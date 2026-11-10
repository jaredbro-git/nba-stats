import SwiftUI

/// A game: prediction, why, expected box scores with Out switches, matchups, and the real box score once it starts.
struct GameView: View {
    let gameId: String
    var body: some View {
        WithLeague { lg in
            if let g = lg.games.first(where: { $0.id == gameId }) { GameContent(lg: lg, game: g) } else { Text("Game not found") }
        }
        .navigationTitle("Game")
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct EstimatePair: Identifiable, Hashable { let shooter, defender: Int; var id: String { "\(shooter)-\(defender)" } }

private struct GameContent: View {
    let lg: League
    let game: Game
    @Environment(AppModel.self) private var model
    @State private var out: Set<Int>?
    @State private var overrides: [Int: Int] = [:]
    @State private var estimate: EstimatePair?
    @State private var box: [Int: [Nba.BoxLine]]?
    @State private var boxError: String?

    var body: some View {
        let _ = model.generation
        let rosterIds = Set((lg.roster(game.homeId) + lg.roster(game.awayId)).map(\.id))
        let saved = model.out(for: game, lg).intersection(rosterIds)
        let current = out ?? saved
        let p = lg.predict(home: game.homeId, away: game.awayId, out: current, usDate: game.usDate, neutral: game.neutral,
                           overrides: overrides, withMatchups: true)
        let n = model.now(game)
        let home = lg.teams[game.homeId], away = lg.teams[game.awayId]
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text([game.kind == "001" ? "Preseason" : game.kind == "004" ? "Playoffs" : "Regular season", game.sublabel.isEmpty ? nil : game.sublabel,
                      game.start.map { "\($0.nzDay), \($0.nzTime) NZ" }, game.arena.isEmpty ? nil : "\(game.arena), \(game.city)"]
                    .compactMap { $0 }.joined(separator: " · "))
                    .font(.footnote).foregroundStyle(.secondary)
                if n.status >= 2 {
                    Text("\(n.status == 2 ? "Live" : "Final"): \(away?.nickname ?? "") \(n.away) – \(n.home) \(home?.nickname ?? "")\(n.status == 2 ? " · \(n.text)" : "")")
                        .font(.subheadline.weight(.semibold)).padding(12).frame(maxWidth: .infinity, alignment: .leading)
                        .glassEffect(.regular.tint(n.status == 2 ? .red.opacity(0.25) : .clear), in: .rect(cornerRadius: 16))
                }
                header(p, home: home, away: away)
                factors(p, home: home)
                comparison(p, home: home, away: away)
                whoIsOut(saved: saved, current: current, rosterIds: rosterIds)
                ForEach([p.away, p.home], id: \.teamId) { side in expectedBox(side, current: current) }
                matchups(p)
                if n.status >= 2 { boxScore(live: n.status == 2) }
            }
            .padding()
        }
        .background(Color(.systemGroupedBackground))
        .sheet(item: $estimate) { e in EstimateSheet(lg: lg, shooter: e.shooter, defender: e.defender) }
        .task(id: n.status) {
            guard n.status >= 2 else { return }
            do { box = try await Nba.boxScore(game.id, ttl: n.status == 2 ? 45 : Nba.day) } catch { boxError = error.localizedDescription }
        }
    }

    private func header(_ p: Prediction, home: Team?, away: Team?) -> some View {
        VStack(spacing: 12) {
            HStack(alignment: .top) {
                ForEach([(p.away, away, 1 - p.homeWin), (p.home, home, p.homeWin)], id: \.0.teamId) { side, team, win in
                    NavigationLink(value: Route.team(side.teamId)) {
                        VStack(spacing: 4) {
                            TeamBadge(team: team, size: 48)
                            Text(team?.nickname ?? "").font(.subheadline)
                            Text(whole(side.pts)).font(.system(size: 40, weight: .bold)).monospacedDigit()
                            Text("\(pct(win)) to win").font(.footnote).foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.plain)
                    if side === p.away { Text("@").font(.title3).foregroundStyle(.secondary).padding(.top, 60) }
                }
            }
            WinBar(awayWin: 1 - p.homeWin)
            Text("Expected margin: \(p.margin > 0 ? home?.nickname ?? "" : away?.nickname ?? "") by \(String(format: "%.1f", abs(p.margin))) · \(whole(p.pace)) possessions")
                .font(.footnote).foregroundStyle(.secondary)
        }
        .padding(16)
        .glassEffect(.regular, in: .rect(cornerRadius: 24))
    }

    private func factors(_ p: Prediction, home: Team?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHead(title: "How the margin is built", note: "Points to the \(home?.nickname ?? "home team"). Real results land within about ±13 points of the expected margin two times in three.")
            ForEach(p.factors.indices, id: \.self) { i in
                StatRow(label: p.factors[i].0, values: [signed(p.factors[i].1)], colors: [tone(p.factors[i].1)])
            }
            Divider()
            StatRow(label: "Expected margin", values: [signed(p.margin)], bold: true)
        }
        .card()
    }

    private func comparison(_ p: Prediction, home: Team?, away: Team?) -> some View {
        func r(_ s: Side) -> (Double, Double, Double) { (lg.leagueOrtg + s.strength.off, lg.leagueOrtg - s.strength.def, s.strength.net) }
        let a = r(p.away), h = r(p.home)
        return VStack(alignment: .leading, spacing: 8) {
            SectionHead(title: "Team comparison", note: "Projected for the players available in this game.")
            StatRow(label: "", values: [away?.abbr ?? "", home?.abbr ?? ""], header: true)
            StatRow(label: "Record", values: [recordText(lg, game.awayId).replacingOccurrences(of: " last season", with: ""),
                                              recordText(lg, game.homeId).replacingOccurrences(of: " last season", with: "")])
            StatRow(label: "Offence", values: [one(a.0), one(h.0)], colors: [a.0 > h.0 ? .green : nil, h.0 > a.0 ? .green : nil])
            StatRow(label: "Defence (lower is better)", values: [one(a.1), one(h.1)], colors: [a.1 < h.1 ? .green : nil, h.1 < a.1 ? .green : nil])
            StatRow(label: "Net rating", values: [signed(a.2), signed(h.2)], colors: [a.2 > h.2 ? .green : nil, h.2 > a.2 ? .green : nil])
            StatRow(label: "Pace", values: [one(lg.leaguePace + p.away.strength.pace), one(lg.leaguePace + p.home.strength.pace)])
            StatRow(label: "Back-to-back", values: [p.away.b2b ? "Yes" : "No", p.home.b2b ? "Yes" : "No"])
        }
        .card()
    }

    @ViewBuilder private func whoIsOut(saved: Set<Int>, current: Set<Int>, rosterIds: Set<Int>) -> some View {
        let names = { (ids: Set<Int>) in ids.compactMap { lg.players[$0]?.name }.sorted().joined(separator: ", ") }
        VStack(alignment: .leading, spacing: 8) {
            SectionHead(title: "Who's out")
            if lg.gameOuts[game.id] != nil {
                Text("Set for this game on your Mac: \(saved.isEmpty ? "everyone available" : names(saved)).").font(.subheadline)
            } else {
                let mine = saved.intersection(model.unavailable(lg)), report = saved.subtracting(mine)
                if saved.isEmpty { Text("Everyone is available.").font(.subheadline) }
                if !mine.isEmpty { Text("From your list: \(names(mine)).").font(.subheadline) }
                if !report.isEmpty { Text("From the NBA injury report: \(names(report)).").font(.subheadline) }
                let doubts = rosterIds.filter { !saved.contains($0) && ["Questionable", "Probable"].contains(lg.injuryNotes[$0]?.status ?? "") }
                if !doubts.isEmpty {
                    Text("On the report but counted as playing: \(doubts.compactMap { pid in lg.players[pid].map { "\($0.name) (\(lg.injuryNotes[pid]!.status.lowercased()))" } }.sorted().joined(separator: ", ")).")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let t = lg.injuryPublished { Text("Injury report from \(t.nzDay), \(t.nzTime) NZ, \(model.injuriesOnPhone ? "read by this iPhone" : "from your Mac's last copy").").font(.caption).foregroundStyle(.secondary) }
            }
            Text("Switch players off in the expected box scores below to see the prediction without them: the prediction updates straight away. Their minutes go to teammates and the team rating moves by each player's estimated impact.")
                .font(.caption).foregroundStyle(.secondary)
            if current != saved {
                Text("Showing: \(current.isEmpty ? "everyone available" : names(current)) (this game only, not saved).").font(.footnote.weight(.semibold))
                HStack {
                    Button("Save for all games") {
                        let changed = rosterIds.filter { current.contains($0) != saved.contains($0) }
                        model.setOut(lg, Array(changed.filter { current.contains($0) }), out: true)
                        model.setOut(lg, Array(changed.filter { !current.contains($0) }), out: false)
                        out = nil
                    }
                    .buttonStyle(.glassProminent)
                    Button("Undo") { out = nil }.buttonStyle(.glass)
                }
            }
        }
        .card()
    }

    private func expectedBox(_ side: Side, current: Set<Int>) -> some View {
        let team = lg.teams[side.teamId]
        let playing = Set(side.lines.map(\.player.id))
        let others = lg.roster(side.teamId).filter { !playing.contains($0.id) }.stableSorted { a, b in
            current.contains(a.id) != current.contains(b.id) ? current.contains(a.id) : a.mpg > b.mpg
        }
        return VStack(alignment: .leading, spacing: 6) {
            SectionHead(title: "\(team?.nickname ?? "") · expected box score")
            StatRow(label: "Player", values: ["MIN", "PTS", "REB", "AST"], header: true)
            ForEach(side.lines, id: \.player.id) { l in
                HStack(spacing: 8) {
                    Toggle("", isOn: Binding(get: { true }, set: { _ in toggle(l.player.id, current) })).labelsHidden().controlSize(.mini).scaleEffect(0.8)
                    NavigationLink(value: Route.player(l.player.id)) {
                        StatRow(label: l.player.name, values: [whole(l.min), one(l["PTS"]), one(l["REB"]), one(l["AST"])])
                    }
                    .buttonStyle(.plain)
                }
            }
            ForEach(others) { pl in
                let isOut = current.contains(pl.id)
                HStack(spacing: 8) {
                    Toggle("", isOn: Binding(get: { !isOut }, set: { _ in toggle(pl.id, current) })).labelsHidden().controlSize(.mini).scaleEffect(0.8)
                    Text("\(pl.name) · \(isOut ? "Out" : "outside the rotation")").font(.subheadline)
                        .foregroundStyle(isOut ? .red : .secondary).strikethrough(isOut)
                    if let note = lg.injuryNotes[pl.id] { InjuryLabel(note: note, compact: true) }
                }
            }
            Divider()
            StatRow(label: "Team", values: ["240", one(side.pts), one(side.lines.reduce(0) { $0 + $1["REB"] }), one(side.lines.reduce(0) { $0 + $1["AST"] })], bold: true)
        }
        .card()
    }

    private func toggle(_ pid: Int, _ current: Set<Int>) {
        var next = current
        if next.contains(pid) { next.remove(pid) } else { next.insert(pid) }
        out = next
    }

    @ViewBuilder private func matchups(_ p: Prediction) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHead(title: "Matchups", note: "Each side's main scorers and the defender most likely to guard them. Pick another defender to see how the prediction changes.")
            ForEach(["away", "home"], id: \.self) { key in
                if let mu = p.matchups[key] {
                    Text("\(lg.teams[key == "away" ? game.awayId : game.homeId]?.nickname ?? "") scorers").font(.caption).foregroundStyle(.secondary)
                    ForEach(mu.rows) { r in matchupRow(r, defenders: mu.defenders) }
                }
            }
            if !overrides.isEmpty { Button("Reset to likely matchups") { overrides = [:] }.buttonStyle(.glass) }
        }
        .card()
    }

    private func matchupRow(_ r: MatchupRow, defenders: [Int]) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(r.shooter.name).fontWeight(.semibold)
                Spacer()
                Text("\(one(r.pts)) pts").fontWeight(.semibold).monospacedDigit()
                if r.changed && abs(r.change) >= 0.05 { Text("(\(signed(r.change)))").font(.caption).foregroundStyle(r.change > 0 ? .green : .red) }
            }
            HStack {
                Text("Guarded by").font(.caption).foregroundStyle(.secondary)
                Menu {
                    ForEach(defenders, id: \.self) { d in
                        Button((lg.players[d]?.name ?? "\(d)") + (d == r.likely ? " (likely)" : "")) { overrides[r.shooter.id] = d }
                    }
                    Button("No specific defender") { overrides[r.shooter.id] = 0 }
                } label: {
                    Text((r.chosen == 0 ? "No specific defender" : lg.players[r.chosen]?.name ?? "?") + (r.changed ? "" : " (likely)")).font(.subheadline)
                }
                .buttonStyle(.glass)
                if r.chosen != 0 { Button("Expected") { estimate = EstimatePair(shooter: r.shooter.id, defender: r.chosen) }.font(.subheadline) }
            }
            Group {
                if let h = r.history {
                    Text("\(h.fgm)/\(h.fga) FG, \(h.pts) pts on \(whole(h.poss)) possessions in \(h.gp) games against each other. Est. \(signed(r.vsAverage)) pts vs an average defender.")
                } else if r.chosen != 0 {
                    Text("Never matched up: uses \(lg.players[r.chosen]?.name ?? "his")'s defensive rating. Est. \(signed(r.vsAverage)) pts vs an average defender.")
                } else { Text("Team defence, no specific defender.") }
            }
            .font(.caption).foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder private func boxScore(live: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHead(title: live ? "Box score (live)" : "Box score")
            if let box {
                ForEach([game.awayId, game.homeId], id: \.self) { tid in
                    Text(lg.teams[tid]?.nickname ?? "").font(.caption).foregroundStyle(.secondary).padding(.top, 4)
                    StatRow(label: "Player", values: ["MIN", "PTS", "REB", "AST", "+/−"], header: true)
                    ForEach(box[tid] ?? []) { l in
                        NavigationLink(value: Route.player(l.id)) {
                            StatRow(label: l.name, values: [String(l.minutes.split(separator: ":").first ?? ""), "\(l.pts)", "\(l.reb)", "\(l.ast)", signed(l.plusMinus, 0)])
                        }
                        .buttonStyle(.plain)
                    }
                }
            } else if let boxError { Text("Couldn't load the box score: \(boxError)").font(.footnote) }
            else { LoadingView() }
        }
        .card()
    }
}
