import SwiftUI

private enum Sort: String, CaseIterable, Identifiable {
    case points = "Points", impact = "Impact", defense = "Matchup D", shooting = "True shooting", usage = "Usage", minutes = "Minutes", youngest = "Youngest"
    var id: String { rawValue }
    var ascending: Bool { self == .defense || self == .youngest }
}

private let groups = ["G": "Guards", "G-F": "Guards", "F-G": "Wings", "F": "Wings", "F-C": "Bigs", "C-F": "Bigs", "C": "Bigs"]

/// Every rostered player, sortable and filterable, plus a search for anyone (retired players included).
struct PlayersView: View {
    var body: some View {
        WithLeague { lg in PlayersList(lg: lg) }
            .navigationTitle("Players")
            .toolbar { SyncButton() }
    }
}

private struct PlayersList: View {
    let lg: League
    @State private var query = ""
    @State private var sort = Sort.points
    @State private var team: Int?
    @State private var group = "All"
    @State private var minMinutes = 20.0

    private func line(_ p: Player) -> [String: Double]? { p.perGame[lg.cur] ?? p.perGame[lg.prev] }
    private func value(_ p: Player) -> Double? {
        switch sort {
        case .points: return line(p)?["PTS"]
        case .impact: return p.impact
        case .defense: return p.defRating.map { $0 * 100 }
        case .shooting: return p.ts
        case .usage: return p.usg
        case .minutes: return line(p)?["MIN"]
        case .youngest: return p.age
        }
    }

    var body: some View {
        let words = League.fold(query).split(separator: " ").map(String.init)
        let rows = lg.playerOrder.compactMap { lg.players[$0] }
            .filter { $0.teamId != nil }
            .filter { team == nil || $0.teamId == team }
            .filter { group == "All" || groups[$0.position] == group }
            .filter { (line($0)?["MIN"] ?? 0) >= minMinutes || !words.isEmpty }
            .filter { p in words.allSatisfy { League.fold(p.name).contains($0) } }
            .stableSorted { a, b in
                switch (value(a), value(b)) {
                case (nil, _): return false
                case (_, nil): return true
                case let (x?, y?): return sort.ascending ? x < y : x > y
                }
            }
        let others = query.count >= 2 ? lg.search(query).filter { lg.players[$0.id]?.teamId == nil } : []
        List {
            Section {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack {
                        Menu(sort.rawValue) { Picker("Sort", selection: $sort) { ForEach(Sort.allCases) { Text($0.rawValue).tag($0) } } }
                        Menu(team.flatMap { lg.teams[$0]?.abbr } ?? "All teams") {
                            Button("All teams") { team = nil }
                            ForEach(lg.teams.values.sorted { $0.name < $1.name }) { t in Button(t.name) { team = t.id } }
                        }
                        Menu(group) { ForEach(["All", "Guards", "Wings", "Bigs"], id: \.self) { g in Button(g) { group = g } } }
                        Menu(minMinutes == 0 ? "Any minutes" : "\(Int(minMinutes))+ min") {
                            ForEach([0.0, 10, 20, 28], id: \.self) { m in Button(m == 0 ? "Any minutes" : "\(Int(m))+ min") { minMinutes = m } }
                        }
                    }
                    .buttonStyle(.glass)
                }
                Text("\(rows.count) players · \(sort.rawValue)\(sort == .defense ? " (points per 100 his matchups score vs usual; lower is better)" : "")")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .listRowBackground(Color.clear)
            Section {
                ForEach(rows) { p in
                    NavigationLink(value: Route.player(p.id)) {
                        HStack(spacing: 10) {
                            TeamBadge(team: p.teamId.flatMap { lg.teams[$0] }, size: 30)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(p.name).fontWeight(.semibold)
                                Text([p.position.isEmpty ? nil : p.position, line(p).map { "\(one($0["MIN"])) min · \(one($0["PTS"])) pts · \(one($0["REB"])) reb · \(one($0["AST"])) ast" }]
                                    .compactMap { $0 }.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(display(value(p))).fontWeight(.semibold).monospacedDigit()
                        }
                    }
                }
            }
            if !others.isEmpty {
                Section("Other players") {
                    ForEach(others, id: \.id) { o in NavigationLink(o.name, value: Route.player(o.id)) }
                }
            }
        }
        .searchable(text: $query, prompt: "Find a player")
    }

    private func display(_ v: Double?) -> String {
        switch sort {
        case .points, .minutes: return one(v)
        case .impact, .defense: return signed(v)
        case .shooting, .usage: return pct(v, 1)
        case .youngest: return v.map { "\(Int($0))" } ?? "–"
        }
    }
}
