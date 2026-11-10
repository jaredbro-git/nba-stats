import SwiftUI

/// The prediction tracker: each game's prediction saved before tip-off (by the Mac or this phone), scored once it's final.
struct TrackerView: View {
    var body: some View {
        WithLeague { lg in TrackerContent(lg: lg) }
            .navigationTitle("Prediction tracker")
            .toolbar { SyncButton() }
    }
}

private let resultSorts: [(String, ([Tracker.Scored]) -> [Tracker.Scored])] = [
    ("Newest first", { $0.stableSorted { $0.p.start > $1.p.start } }),
    ("Oldest first", { $0.stableSorted { $0.p.start < $1.p.start } }),
    ("Biggest margin miss", { $0.stableSorted { abs($0.marginError ?? 0) > abs($1.marginError ?? 0) } }),
    ("Closest call", { $0.stableSorted { abs($0.marginError ?? 0) < abs($1.marginError ?? 0) } }),
    ("Biggest favourite", { $0.stableSorted { $0.favouriteChance > $1.favouriteChance } }),
]

private struct TrackerContent: View {
    let lg: League
    @Environment(AppModel.self) private var model
    @State private var kind: String?
    @State private var backfilled = true
    @State private var search = ""
    @State private var day: String?
    @State private var minFav = 0
    @State private var outcome = "All"
    @State private var sort = "Newest first"

    var body: some View {
        let _ = model.generation
        let saved = model.picks(lg)
        let kinds = Tracker.kinds.map(\.key).filter { k in saved.contains { $0.kind == k } }
        let chosen = kind.flatMap { kinds.contains($0) ? $0 : nil } ?? kinds.first ?? "reg"
        let games = Dictionary(uniqueKeysWithValues: lg.games.map { ($0.id, $0) })
        // The final score: the Mac's record, else the game (live scores or the copied data) once it's over.
        let mine = saved.filter { $0.kind == chosen && (backfilled || !$0.backfilled) }.map { p -> Tracker.Scored in
            if let r = p.result { return Tracker.Scored(p: p, result: r) }
            if let g = games[p.gameId] { let n = model.now(g); if n.status == 3 { return Tracker.Scored(p: p, result: (n.home, n.away)) } }
            return Tracker.Scored(p: p, result: nil)
        }
        let summary = Tracker.summary(mine)
        let tracked = Set(saved.map(\.gameId))
        let untracked = lg.games.filter { model.now($0).status == 3 && Tracker.kindOf($0.id) == chosen && !tracked.contains($0.id) }.count

        let words = League.fold(search).split(separator: " ").map(String.init)
        let teamText = { (id: Int) -> String in lg.teams[id].map { League.fold("\($0.abbr) \($0.name) \($0.nickname)") } ?? "" }
        let matches = { (s: Tracker.Scored) -> Bool in
            let text = teamText(s.p.homeId) + " " + teamText(s.p.awayId)
            return words.allSatisfy { text.contains($0) } && (day == nil || s.p.start.nzDate == day) && s.favouriteChance * 100 >= Double(minFav)
        }
        let allUpcoming = mine.filter { $0.result == nil }, allFinished = mine.filter { $0.result != nil }
        let upcoming = allUpcoming.filter(matches).stableSorted { $0.p.start < $1.p.start }
        let finished = (resultSorts.first { $0.0 == sort }?.1 ?? resultSorts[0].1)(
            allFinished.filter { matches($0) && (outcome == "All" || ($0.correct == true) == (outcome == "Right")) })
        let days = Array(Set(mine.map { $0.p.start.nzDate })).sorted()
        let filtering = !words.isEmpty || day != nil || minFav > 0

        List {
            Section {
                Text("Each game's prediction is saved before tip-off, by this iPhone or your Mac, and scored once the game is final.").font(.footnote).foregroundStyle(.secondary)
                if kinds.count > 1 {
                    Picker("Games", selection: Binding(get: { chosen }, set: { kind = $0 })) { ForEach(kinds, id: \.self) { Text(Tracker.label($0)).tag($0) } }
                        .pickerStyle(.segmented)
                }
                if chosen == "pre" {
                    Text("Preseason is scored separately: starters play short minutes and coaches test rotations, so these results say more about preseason than about the model.")
                        .font(.footnote)
                    if saved.contains(where: { $0.kind == "pre" && $0.backfilled }) {
                        Toggle("Include backfilled games (predicted afterwards, before any regular-season data)", isOn: $backfilled).font(.footnote)
                    }
                }
            }
            if let summary {
                Section {
                    Tiles(tiles: [
                        Tile(value: pct(summary.accuracy), label: "Winners picked", sub: "\(Int((summary.accuracy * Double(summary.games)).rounded())) of \(summary.games) games"),
                        Tile(value: String(format: "%.1f", summary.marginError), label: "Average margin miss", sub: "points off the final margin"),
                        Tile(value: String(format: "%.1f", summary.totalError), label: "Average total miss", sub: "points off the combined score"),
                        Tile(value: String(format: "%.3f", summary.brier), label: "Brier score", sub: "0.25 = coin flip; lower is better"),
                    ])
                }
                .listRowBackground(Color.clear).listRowInsets(EdgeInsets())
                Section {
                    StatRow(label: "Favourite's chance", values: ["Games", "Pred.", "Won"], header: true)
                    ForEach(summary.bins) { b in
                        VStack(spacing: 4) {
                            StatRow(label: "\(Int(b.lo * 100))–\(min(100, Int(b.hi * 100)))%", values: ["\(b.games)", pct(b.expected), pct(b.rate)])
                            if let rate = b.rate, let exp = b.expected {
                                GeometryReader { geo in
                                    ZStack(alignment: .leading) {
                                        Capsule().fill(.quaternary)
                                        Capsule().fill(.tint).frame(width: geo.size.width * rate)
                                        Rectangle().fill(.primary).frame(width: 2).offset(x: geo.size.width * exp - 1)
                                    }
                                }
                                .frame(height: 6)
                            }
                        }
                    }
                } header: { Text("Do favourites win as often as predicted?") } footer: {
                    Text("Bars show how often favourites won; the marker is how often they were expected to. With only a few games per row, expect big swings.")
                }
                Section {
                    Text("\(summary.games) finished game\(summary.games == 1 ? "" : "s") scored\(untracked > 0 ? ", \(untracked) not tracked" : "").")
                    Text(lg.howTracked).font(.caption).foregroundStyle(.secondary)
                } header: { Text("Coverage") }
            } else {
                Section {
                    Text(allUpcoming.isEmpty ? "No saved predictions yet." : "No finished games with a saved prediction yet: the first results come in after \(allUpcoming.map(\.p.start).min()!.nzDay).")
                    if untracked > 0 { Text("\(untracked) finished game\(untracked == 1 ? " wasn't" : "s weren't") tracked: NBA Stats wasn't open on the Mac in the week before.") }
                    Text(lg.howTracked).font(.caption).foregroundStyle(.secondary)
                }
            }
            if !mine.isEmpty {
                Section("Find games") {
                    TextField("Team, e.g. Lakers or BOS", text: $search).autocorrectionDisabled()
                    Picker("Date", selection: $day) {
                        Text("All dates").tag(String?.none)
                        ForEach(days, id: \.self) { d in Text(dayLabel(d)).tag(Optional(d)) }
                    }
                    Picker("Favourite's chance", selection: $minFav) { ForEach([0, 60, 70, 80], id: \.self) { Text($0 == 0 ? "Any" : "\($0)%+").tag($0) } }
                    if filtering { Button("Clear") { search = ""; day = nil; minFav = 0 } }
                }
            }
            if !allUpcoming.isEmpty {
                Section {
                    if upcoming.isEmpty { Text("No upcoming games match.").foregroundStyle(.secondary) }
                    ForEach(upcoming) { s in NavigationLink(value: Route.game(s.p.gameId)) { SavedLine(lg: lg, s: s) } }
                } header: { Text(filtering ? "Upcoming · \(upcoming.count) of \(allUpcoming.count)" : "Upcoming · redone until tip-off, then locked in") }
            }
            if !allFinished.isEmpty {
                Section {
                    Picker("Prediction", selection: $outcome) { ForEach(["All", "Right", "Wrong"], id: \.self) { Text($0 == "All" ? "Right and wrong" : $0).tag($0) } }
                    Picker("Sort", selection: $sort) { ForEach(resultSorts.map(\.0), id: \.self) { Text($0).tag($0) } }
                    if finished.isEmpty { Text("No results match.").foregroundStyle(.secondary) }
                    ForEach(finished) { s in NavigationLink(value: Route.game(s.p.gameId)) { SavedLine(lg: lg, s: s) } }
                } header: { Text(filtering || outcome != "All" ? "Results · \(finished.count) of \(allFinished.count)" : "Results") }
            }
        }
    }

    private func dayLabel(_ d: String) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = AppModel.tz
        return f.date(from: d)?.addingTimeInterval(12 * 3600).nzDay ?? d
    }
}

private struct SavedLine: View {
    let lg: League
    let s: Tracker.Scored
    var body: some View {
        let p = s.p
        let home = lg.teams[p.homeId], away = lg.teams[p.awayId]
        let fav = p.homeWin >= 0.5 ? home : away
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    TeamBadge(team: away, size: 24); Text(away?.abbr ?? "").fontWeight(.semibold)
                    Text("@").foregroundStyle(.secondary)
                    TeamBadge(team: home, size: 24); Text(home?.abbr ?? "").fontWeight(.semibold)
                }
                Text([p.start.nzDay + (s.result == nil ? ", \(p.start.nzTime)" : ""), "predicted \(whole(p.awayPts))–\(whole(p.homePts))", p.backfilled ? "backfilled" : nil]
                    .compactMap { $0 }.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 1) {
                if let r = s.result {
                    Text("\(r.away)–\(r.home)").font(.headline).monospacedDigit()
                    Text(s.correct == true ? "✓ Right" : "✗ Wrong").font(.caption.weight(.semibold)).foregroundStyle(s.correct == true ? .green : .red)
                    Text("\(fav?.abbr ?? "") \(pct(s.favouriteChance)) · miss \(signed(s.marginError))").font(.caption2).foregroundStyle(.secondary)
                } else {
                    Text("\(fav?.abbr ?? "") \(pct(s.favouriteChance))").fontWeight(.semibold)
                    if p.start <= Date() {
                        Label(p.byPhone ? "Locked in · iPhone" : "Locked in", systemImage: "lock.fill").font(.caption2.weight(.semibold))
                    } else if let logged = p.loggedAt {
                        Label("updating · \(logged.nzDay.split(separator: " ").first ?? "") \(logged.nzTime)\(p.byPhone ? " · iPhone" : "")", systemImage: "lock.open").font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }
}
