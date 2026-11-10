import SwiftUI

/// One NZ day's games: live scores, predictions (the one saved before tip-off once a game starts) and results.
struct TodayView: View {
    var body: some View {
        WithLeague { lg in TodayContent(lg: lg) }
            .navigationTitle("Today")
            .toolbar { SyncButton() }
    }
}

private struct Card: Identifiable {
    let game: Game
    let status: Int
    let text: String
    let awayScore, homeScore: Int
    let homePts, awayPts, homeWin: Double
    let source: String          // "saved" (before tip-off), "now", or "untracked"
    let out: [Int: [String]]    // team id -> names
    let ownList: Bool
    let savedAt: Date?          // when this game's pick was last saved
    let savedBy: String?        // "iPhone" or "Mac"
    var id: String { game.id }
    var correct: Bool? { status == 3 && source == "saved" ? (homeWin >= 0.5) == (homeScore > awayScore) : nil }
}

private struct TodayContent: View {
    let lg: League
    @Environment(AppModel.self) private var model
    @State private var day: String = Date().nzDate

    /// NZ days that have games between known teams.
    private var days: [String] {
        Array(Set(lg.games.filter { lg.teams[$0.homeId] != nil && lg.teams[$0.awayId] != nil }.compactMap { $0.start?.nzDate })).sorted()
    }

    private func cards() -> [Card] {
        let saved = Dictionary(model.picks(lg).map { ($0.gameId, $0) }, uniquingKeysWith: { a, _ in a })
        return lg.games.filter { $0.start?.nzDate == day && lg.teams[$0.homeId] != nil && lg.teams[$0.awayId] != nil }.map { g in
            let n = model.now(g)
            let out = model.out(for: g, lg)
            let rec = saved[g.id]
            var homePts: Double, awayPts: Double, homeWin: Double, source: String
            if n.status >= 2, let rec {
                (homePts, awayPts, homeWin, source) = (rec.homePts, rec.awayPts, rec.homeWin, "saved")
            } else {
                let p = lg.predict(home: g.homeId, away: g.awayId, out: out, usDate: g.usDate, neutral: g.neutral)
                (homePts, awayPts, homeWin, source) = (p.home.pts, p.away.pts, p.homeWin, n.status == 1 ? "now" : "untracked")
            }
            var names: [Int: [String]] = [:]
            for pid in out { if let p = lg.players[pid], let t = p.teamId { names[t, default: []].append(p.name) } }
            return Card(game: g, status: n.status, text: n.text, awayScore: n.away, homeScore: n.home, homePts: homePts, awayPts: awayPts,
                        homeWin: homeWin, source: source, out: names, ownList: lg.gameOuts[g.id] != nil, savedAt: rec?.loggedAt,
                        savedBy: rec.map { $0.byPhone ? "iPhone" : "Mac" })
        }
    }

    var body: some View {
        let _ = model.generation
        let list = cards()
        let scored = list.compactMap(\.correct)
        let prev = days.last { $0 < day }, next = days.first { $0 > day }
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Button { if let prev { day = prev } } label: { Image(systemName: "chevron.left") }
                        .buttonStyle(.glass).disabled(prev == nil)
                    Spacer()
                    VStack(spacing: 0) {
                        Text(dayTitle).font(.headline)
                        if day != Date().nzDate { Button("Back to today") { day = Date().nzDate }.font(.caption) }
                    }
                    Spacer()
                    Button { if let next { day = next } } label: { Image(systemName: "chevron.right") }
                        .buttonStyle(.glass).disabled(next == nil)
                }
                if list.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("No games on this day.")
                        if let next { Button("Next games ›") { day = next } }
                    }
                    .card()
                } else {
                    Tiles(tiles: [
                        Tile(value: "\(list.count)", label: "Games", sub: model.anyLive ? "\(list.filter { $0.status == 2 }.count) live now" : "\(list.filter { $0.status == 3 }.count) finished"),
                        Tile(value: scored.isEmpty ? "–" : "\(scored.filter { $0 }.count)/\(scored.count)", label: "Picks right",
                             sub: scored.isEmpty ? "none finished yet" : "saved before tip-off"),
                    ])
                    ForEach(list) { c in NavigationLink(value: Route.game(c.id)) { GameCard(card: c, lg: lg) }.buttonStyle(.plain) }
                    Text("Before tip-off, predictions use the latest data and who's out. Picks are saved up to 7 days ahead and redone on every update (new results, injury reports) until tip-off, by this iPhone and by your Mac while it's awake. The one saved nearest tip-off is locked in, and that's what the Tracker scores.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let updated = model.liveUpdated { Text("Scores from stats.nba.com, updated \(updated.nzTime).").font(.caption).foregroundStyle(.secondary) }
            }
            .padding()
        }
        .background(GlassBackdrop())
        .refreshable { await model.refreshLive() }
        .onAppear {
            // Today, or the next day with games.
            if !days.contains(day), let next = days.first(where: { $0 >= day }) { day = next }
        }
    }

    private var dayTitle: String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = AppModel.tz
        return f.date(from: day)?.addingTimeInterval(12 * 3600).nzLongDay ?? day
    }
}

private struct GameCard: View {
    let card: Card
    let lg: League

    var body: some View {
        let favHome = card.homeWin >= 0.5
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Group {
                    if card.status == 2 { Label(card.text.isEmpty ? "Live" : card.text, systemImage: "dot.radiowaves.left.and.right").foregroundStyle(.white).background(Capsule().fill(.red).padding(-6)) }
                    else if card.status == 3 { Text("Final") }
                    else { Text(card.game.start?.nzTime ?? "TBD") }
                }
                .font(.caption.weight(.semibold)).padding(.horizontal, 6)
                Spacer()
                Text([card.game.kind == "001" ? "Preseason" : card.game.kind == "004" ? "Playoffs" : nil, card.game.sublabel.isEmpty ? nil : card.game.sublabel]
                    .compactMap { $0 }.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
            }
            ForEach([(card.game.awayId, false), (card.game.homeId, true)], id: \.0) { tid, isHome in
                let team = lg.teams[tid]
                let won = card.status == 3 && (isHome ? card.homeScore > card.awayScore : card.awayScore > card.homeScore)
                HStack(spacing: 10) {
                    TeamBadge(team: team, size: 34)
                    VStack(alignment: .leading, spacing: 0) {
                        Text(team?.nickname ?? "TBD").font(.headline)
                        Text(recordText(lg, tid)).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    if card.status >= 2 {
                        Text("\(isHome ? card.homeScore : card.awayScore)").font(.title.weight(.bold)).monospacedDigit()
                            .foregroundStyle(card.status == 3 && !won ? .secondary : .primary)
                    } else {
                        Text(pct(isHome ? card.homeWin : 1 - card.homeWin)).font(.title3.weight(isHome == favHome ? .bold : .regular)).monospacedDigit()
                            .foregroundStyle(isHome == favHome ? .primary : .secondary)
                    }
                }
            }
            WinBar(awayWin: 1 - card.homeWin, height: 6)
            VStack(alignment: .leading, spacing: 2) {
                let fav = lg.teams[favHome ? card.game.homeId : card.game.awayId]
                Text("\(card.source == "saved" ? "Predicted before tip-off" : card.source == "untracked" ? "Not tracked · model now says" : "Predicted"): ")
                    .foregroundStyle(.secondary)
                + Text("\(whole(card.awayPts))–\(whole(card.homePts)), \(fav?.abbr ?? "") \(pct(max(card.homeWin, 1 - card.homeWin)))").bold()
                PickState(card: card)
                if let correct = card.correct {
                    Text(correct ? "✓ Right" : "✗ Wrong").font(.subheadline.weight(.semibold)).foregroundStyle(correct ? .green : .red)
                }
            }
            .font(.footnote)
            if !card.out.isEmpty || card.ownList {
                Divider()
                VStack(alignment: .leading, spacing: 2) {
                    ForEach([card.game.awayId, card.game.homeId], id: \.self) { tid in
                        if let names = card.out[tid], !names.isEmpty { Text("Out · \(lg.teams[tid]?.abbr ?? ""): \(names.sorted().joined(separator: ", "))") }
                    }
                    if card.ownList { Text(card.out.isEmpty ? "Everyone available (set for this game on your Mac)" : "Set for this game on your Mac").foregroundStyle(.secondary) }
                }
                .font(.caption)
            }
        }
        .padding(16)
        .glassEffect(.regular, in: .rect(cornerRadius: 24))
        .overlay { if card.status == 2 { RoundedRectangle(cornerRadius: 24).strokeBorder(.red.opacity(0.7), lineWidth: 1.5) } }
    }
}

/// A soft colour wash behind glass cards (glass needs something to refract).
struct GlassBackdrop: View {
    @Environment(\.colorScheme) private var scheme
    var body: some View {
        ZStack {
            Color(.systemGroupedBackground)
            RadialGradient(colors: [.blue.opacity(scheme == .dark ? 0.32 : 0.20), .clear], center: .topLeading, startRadius: 0, endRadius: 520)
            RadialGradient(colors: [.orange.opacity(scheme == .dark ? 0.22 : 0.15), .clear], center: .topTrailing, startRadius: 0, endRadius: 460)
            RadialGradient(colors: [.green.opacity(scheme == .dark ? 0.18 : 0.12), .clear], center: .bottom, startRadius: 0, endRadius: 560)
        }
        .ignoresSafeArea()
    }
}

/// Whether the game's pick can still change: updating until tip-off, then locked in.
private struct PickState: View {
    let card: Card
    var body: some View {
        let by = card.savedBy.map { " by your \($0)" } ?? ""
        if card.source == "saved" {
            let start = card.game.start ?? .distantFuture
            let before = start.timeIntervalSince(card.savedAt ?? start)
            Label(before > 1800 ? "Locked in · saved \(ago(before)) before tip-off\(by)" : "Locked in at tip-off\(by)", systemImage: "lock.fill")
                .font(.caption.weight(.semibold))
        } else if card.status == 1, let saved = card.savedAt {
            Label("Updates until tip-off (\(card.game.start?.nzTime ?? "")) · saved \(saved.nzDay.split(separator: " ").first ?? "") \(saved.nzTime)\(by)", systemImage: "lock.open")
                .font(.caption).foregroundStyle(.secondary)
        } else if card.status == 1 {
            Label("Not saved yet · picks are saved within 7 days of tip-off", systemImage: "lock.open")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    private func ago(_ t: TimeInterval) -> String {
        t < 5400 ? "\(Int(t / 60)) min" : t < 48 * 3600 ? "\(Int((t / 3600).rounded())) h" : "\(Int((t / 86400).rounded())) days"
    }
}
