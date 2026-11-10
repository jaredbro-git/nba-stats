import SwiftUI

/// A player's card: bio, numbers, playstyle, plays like, shot chart, matchups and career.
struct PlayerView: View {
    let playerId: Int
    var body: some View {
        WithLeague { lg in PlayerContent(lg: lg, playerId: playerId).navigationTitle(lg.nameOf(playerId)) }
            .navigationBarTitleDisplayMode(.inline)
    }
}

private struct PlayerContent: View {
    let lg: League
    let playerId: Int
    @State private var info: [String: Any]?
    @State private var career: [[String: Any]]?
    @State private var estimate: EstimatePair?

    var body: some View {
        let p = lg.players[playerId]
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 12) {
                    AsyncImage(url: Nba.headshot(playerId)) { img in img.resizable().scaledToFill() } placeholder: { Color.secondary.opacity(0.15) }
                        .frame(width: 104, height: 76).clipShape(.rect(cornerRadius: 14))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(lg.nameOf(playerId)).font(.title2.weight(.bold))
                        let team = p?.teamId.flatMap { lg.teams[$0] }
                        if let team {
                            NavigationLink(value: Route.team(team.id)) {
                                Text([team.name, p?.position.isEmpty == false ? p?.position : nil, p?.number.isEmpty == false ? "#\(p!.number)" : nil].compactMap { $0 }.joined(separator: " · "))
                                    .font(.subheadline)
                            }
                        } else { Text("Not on an NBA roster").font(.subheadline).foregroundStyle(.secondary) }
                    }
                }
                if let info { Text(bio(info)).font(.footnote).foregroundStyle(.secondary) }
                if let p { numbers(p); style(p) }
                ShotsCard(lg: lg, playerId: playerId, career: career)
                MatchupsCard(lg: lg, playerId: playerId, estimate: $estimate)
                if let career, !career.isEmpty { careerCard(career) }
            }
            .padding()
        }
        .background(Color(.systemGroupedBackground))
        .sheet(item: $estimate) { e in EstimateSheet(lg: lg, shooter: e.shooter, defender: e.defender) }
        .task(id: playerId) {
            info = try? await Nba.playerInfo(playerId)
            career = (try? await Nba.career(playerId)) ?? []
        }
    }

    private func bio(_ i: [String: Any]) -> String {
        var parts: [String] = []
        if let b = (i["BIRTHDATE"] as? String)?.prefix(10), let d = ISO8601DateFormatter().date(from: "\(b)T00:00:00Z"),
           let years = Calendar.current.dateComponents([.year], from: d, to: Date()).year { parts.append("Age \(years)") }
        if let h = i["HEIGHT"] as? String, h.contains("-") {
            let f = h.split(separator: "-").compactMap { Double($0) }
            if f.count == 2 { parts.append(heightText(f[0] * 12 + f[1])) }
        }
        if let w = i["WEIGHT"] as? String, !w.isEmpty { parts.append("\(w) lb") }
        if let c = i["COUNTRY"] as? String, !c.isEmpty { parts.append(c) }
        if let s = i["SCHOOL"] as? String, !s.isEmpty { parts.append(s) }
        if let y = i["DRAFT_YEAR"] as? String { parts.append(y == "Undrafted" ? "Undrafted" : "Drafted \(y), pick \(i["DRAFT_NUMBER"] ?? "")") }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder private func numbers(_ p: Player) -> some View {
        let season = p.perGame[lg.cur] != nil ? lg.cur : lg.prev
        if let pg = p.perGame[season] {
            Tiles(tiles: [
                Tile(value: one(pg["PTS"]), label: "Points (\(season))"), Tile(value: one(pg["REB"]), label: "Rebounds"),
                Tile(value: one(pg["AST"]), label: "Assists"), Tile(value: one(pg["MIN"]), label: "Minutes"),
                Tile(value: signed(p.impact), label: "Impact (net per 100)", sub: "off \(signed(p.impactOff)) · def \(signed(p.impactDef))", tone: tone(p.impact, threshold: 0.5)),
                Tile(value: signed(p.defRating.map { $0 * 100 }), label: "Matchup defence", sub: "lower is better",
                     tone: p.defRating.map { $0 < -0.005 ? .green : $0 > 0.005 ? .red : .primary } ?? .primary),
            ])
        }
    }

    @ViewBuilder private func style(_ p: Player) -> some View {
        if let summary = p.summary {
            VStack(alignment: .leading, spacing: 8) {
                SectionHead(title: "Playstyle\(p.styleSeason.map { " · \($0)" } ?? "")")
                Text(summary)
                ForEach(p.traits, id: \.self) { t in
                    VStack(alignment: .leading, spacing: 1) { Text(t.label).fontWeight(.semibold); Text(t.detail).font(.footnote).foregroundStyle(.secondary) }
                }
            }
            .card()
        }
        if !p.similar.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                SectionHead(title: "Plays like", note: "Players whose game looks most like his: shot locations, usage, playmaking, efficiency, rebounding, blocks and steals.")
                ForEach(p.similar, id: \.id) { s in
                    NavigationLink(value: Route.player(s.id)) {
                        HStack { Text(lg.nameOf(s.id)); Spacer(); Text("\(Int(s.match * 100))% match").font(.footnote).foregroundStyle(.secondary) }
                    }
                    .buttonStyle(.plain)
                }
            }
            .card()
        }
    }

    private func careerCard(_ rows: [[String: Any]]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionHead(title: "Regular season")
            StatRow(label: "Season", values: ["Team", "GP", "PTS", "REB", "AST"], header: true)
            ForEach(Array(rows.reversed().enumerated()), id: \.offset) { _, r in
                StatRow(label: "\(r["SEASON_ID"] ?? "")", values: [("\(r["TEAM_ABBREVIATION"] ?? "")" == "TOT" ? "Total" : "\(r["TEAM_ABBREVIATION"] ?? "")"),
                                                                    "\(r["GP"] ?? "")", one(Json.double(r["PTS"])), one(Json.double(r["REB"])), one(Json.double(r["AST"]))])
            }
        }
        .card()
    }
}

private struct ShotsCard: View {
    let lg: League
    let playerId: Int
    let career: [[String: Any]]?
    @State private var season: String?
    @State private var opponent: String?
    @State private var shots: [Shots.Shot]?
    @State private var error: String?

    private var seasons: [String] {
        var seen: [String] = []
        for r in career ?? [] { let s = "\(r["SEASON_ID"] ?? "")"; if s >= "1996-97" && !seen.contains(s) { seen.append(s) } }
        return seen.reversed()
    }

    var body: some View {
        let chosen = season ?? seasons.first
        VStack(alignment: .leading, spacing: 8) {
            SectionHead(title: "Shot chart")
            if career == nil { LoadingView() }
            else if seasons.isEmpty { Text("No NBA shots on record.").font(.footnote).foregroundStyle(.secondary) }
            else {
                HStack {
                    Menu(chosen ?? "") { ForEach(seasons, id: \.self) { s in Button(s) { season = s; opponent = nil } } }
                    let opponents = Array(Set((shots ?? []).map(\.opponent))).sorted()
                    Menu(opponent.map { "vs \($0)" } ?? "All opponents") {
                        Button("All opponents") { opponent = nil }
                        ForEach(opponents, id: \.self) { o in Button(o) { opponent = o } }
                    }
                }
                .buttonStyle(.glass)
                if let shots {
                    if let chart = Shots.chart(opponent == nil ? shots : shots.filter { $0.opponent == opponent }) { ShotChartView(chart: chart) }
                    else { Text("No shots for this selection.").font(.footnote) }
                } else if let error { Text("Couldn't load shots: \(error)").font(.footnote) }
                else { LoadingView(text: "Downloading shots…") }
            }
        }
        .card()
        .task(id: chosen) {
            guard let chosen else { return }
            shots = nil; error = nil
            do {
                let (rows, league) = try await Nba.shots(playerId, season: chosen, current: chosen >= lg.cur)
                shots = Shots.parse(rows, league: league)
            } catch { self.error = error.localizedDescription }
        }
    }
}

private enum MatchupSort: String, CaseIterable { case possessions = "Most possessions", best = "Best first", worst = "Worst first", lowFg = "Lowest FG%", highFg = "Highest FG%" }

private struct MatchupsCard: View {
    let lg: League
    let playerId: Int
    @Binding var estimate: EstimatePair?
    @State private var guarding = false
    @State private var sort = MatchupSort.possessions
    @State private var minPoss = 25.0
    @State private var shown = 15
    @State private var all: [(other: Int, stats: PairStats)]?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHead(title: "Matchups · \(lg.matchups.firstSeason) to now")
            Picker("", selection: $guarding) { Text("Guarded by").tag(false); Text("Guarding").tag(true) }.pickerStyle(.segmented)
            HStack {
                Menu(sort.rawValue) { ForEach(MatchupSort.allCases, id: \.self) { s in Button(s.rawValue) { sort = s } } }
                Menu(minPoss == 0 ? "Any possessions" : "\(Int(minPoss))+ poss.") { ForEach([0.0, 10, 25, 50, 100], id: \.self) { m in Button(m == 0 ? "Any" : "\(Int(m))+") { minPoss = m; shown = 15 } } }
            }
            .buttonStyle(.glass)
            if let all {
                let rows = sorted(all.filter { $0.stats.poss >= minPoss })
                Text("\(rows.count) \(guarding ? "shooters he's guarded" : "defenders who've guarded him"). Effect (per 100 possessions) is sample-adjusted; negative means \(guarding ? "he held them below their usual" : "they held him below his usual"). Tap for the expected outcome.")
                    .font(.caption).foregroundStyle(.secondary)
                StatRow(label: guarding ? "Shooter" : "Defender", values: ["Poss", "FG", "Pts", "Effect"], header: true)
                ForEach(rows.prefix(shown), id: \.other) { o in
                    Button {
                        estimate = guarding ? EstimatePair(shooter: o.other, defender: playerId) : EstimatePair(shooter: playerId, defender: o.other)
                    } label: {
                        StatRow(label: lg.nameOf(o.other), values: [whole(o.stats.poss), "\(o.stats.fgm)/\(o.stats.fga)", "\(o.stats.pts)", signed(o.stats.effect * 100)],
                                colors: [nil, nil, nil, o.stats.effect < -0.005 ? .green : o.stats.effect > 0.005 ? .red : nil])
                    }
                    .buttonStyle(.plain)
                }
                if rows.count > shown { Button("Show more") { shown += 25 } }
            } else { LoadingView() }
        }
        .card()
        .task(id: guarding) {
            all = nil
            let lg = lg, pid = playerId, g = guarding
            all = await Task.detached { lg.matchups.allFor(pid, guarding: g) }.value
            shown = 15
        }
    }

    private func sorted(_ rows: [(other: Int, stats: PairStats)]) -> [(other: Int, stats: PairStats)] {
        func fg(_ s: PairStats) -> Double { Double(s.fgm) / Double(s.fga) }
        switch sort {
        case .possessions: return rows
        case .best: return rows.stableSorted { $0.stats.effect < $1.stats.effect }
        case .worst: return rows.stableSorted { $0.stats.effect > $1.stats.effect }
        case .lowFg: return rows.filter { $0.stats.fga > 0 }.stableSorted { fg($0.stats) < fg($1.stats) }
        case .highFg: return rows.filter { $0.stats.fga > 0 }.stableSorted { fg($0.stats) > fg($1.stats) }
        }
    }
}
