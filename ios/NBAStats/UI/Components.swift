import SwiftUI

/// Pages any tab can open.
enum Route: Hashable {
    case team(Int)
    case game(String)
    case player(Int)
}

extension View {
    /// Every tab's navigation stack opens teams, games and players the same way.
    func appDestinations() -> some View {
        navigationDestination(for: Route.self) { route in
            switch route {
            case .team(let id): TeamView(teamId: id)
            case .game(let id): GameView(gameId: id)
            case .player(let id): PlayerView(playerId: id)
            }
        }
    }

    /// A content card: a rounded panel on the grouped background.
    func card(padding: CGFloat = 16) -> some View {
        self.padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.background.secondary, in: .rect(cornerRadius: 22))
    }
}

// MARK: Formatting

func pct(_ v: Double?, _ digits: Int = 0) -> String { v.map { String(format: "%.\(digits)f%%", $0 * 100) } ?? "–" }
func one(_ v: Double?) -> String { v.map { String(format: "%.1f", $0) } ?? "–" }
func whole(_ v: Double) -> String { String(Int(v.rounded())) }
/// "+1.2", "−0.4", or "0.0" (sign decided after rounding, so never "−0.0").
func signed(_ v: Double?, _ digits: Int = 1) -> String {
    guard let v else { return "–" }
    let text = String(format: "%.\(digits)f", abs(v))
    if Double(text) == 0 { return text }
    return (v > 0 ? "+" : "−") + text
}
func heightText(_ inches: Double?) -> String {
    guard let inches, inches > 0 else { return "–" }
    return "\(Int(inches / 12))′\(Int((inches.truncatingRemainder(dividingBy: 12)).rounded()))″"
}
func tone(_ v: Double, threshold: Double = 0.05) -> Color { v > threshold ? .green : v < -threshold ? .red : .primary }

// MARK: Teams

private let teamColors: [String: UInt32] = [
    "ATL": 0xC8102E, "BOS": 0x007A33, "BKN": 0x333333, "CHA": 0x1D1160, "CHI": 0xCE1141, "CLE": 0x860038,
    "DAL": 0x00538C, "DEN": 0x0E2240, "DET": 0xC8102E, "GSW": 0x1D428A, "HOU": 0xCE1141, "IND": 0x002D62,
    "LAC": 0xC8102E, "LAL": 0x552583, "MEM": 0x5D76A9, "MIA": 0x98002E, "MIL": 0x00471B, "MIN": 0x0C2340,
    "NOP": 0x0C2340, "NYK": 0x006BB6, "OKC": 0x007AC1, "ORL": 0x0077C0, "PHI": 0x006BB6, "PHX": 0x1D1160,
    "POR": 0xE03A3E, "SAC": 0x5A2D81, "SAS": 0x6B7378, "TOR": 0xCE1141, "UTA": 0x002B5C, "WAS": 0x002B5C,
]

func teamColor(_ abbr: String?) -> Color {
    let v = teamColors[abbr ?? ""] ?? 0x555555
    return Color(red: Double((v >> 16) & 0xFF) / 255, green: Double((v >> 8) & 0xFF) / 255, blue: Double(v & 0xFF) / 255)
}

/// A team's abbreviation in a coloured circle (works offline; the NBA's logos are SVG only).
struct TeamBadge: View {
    let team: Team?
    var size: CGFloat = 30
    var body: some View {
        Text(team?.abbr ?? "?")
            .font(.system(size: size * 0.32, weight: .bold))
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(teamColor(team?.abbr), in: .circle)
            .lineLimit(1)
    }
}

/// Two-part bar for a win chance: away share on the left, home on the right.
struct WinBar: View {
    let awayWin: Double
    var height: CGFloat = 10
    var body: some View {
        GeometryReader { geo in
            let a = max(0.01, min(0.99, awayWin))
            HStack(spacing: 2) {
                UnevenRoundedRectangle(topLeadingRadius: 4, bottomLeadingRadius: 4).fill(Color.blue).frame(width: (geo.size.width - 2) * a)
                UnevenRoundedRectangle(bottomTrailingRadius: 4, topTrailingRadius: 4).fill(Color.orange)
            }
        }
        .frame(height: height)
    }
}

// MARK: Numbers

struct Tile: Identifiable {
    let value, label: String
    var sub: String? = nil
    var tone: Color = .primary
    var id: String { label }
}

/// Number tiles, two to a row.
struct Tiles: View {
    let tiles: [Tile]
    var body: some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
            ForEach(tiles) { t in
                VStack(alignment: .leading, spacing: 3) {
                    Text(t.label).font(.footnote).foregroundStyle(.secondary).lineLimit(2)
                    Text(t.value).font(.title2.weight(.semibold)).monospacedDigit().foregroundStyle(t.tone)
                    if let sub = t.sub { Text(sub).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                }
                .frame(maxWidth: .infinity, minHeight: 64, alignment: .leading)
                .padding(12)
                .background(.background.secondary, in: .rect(cornerRadius: 18))
            }
        }
    }
}

/// A section title with an optional note under it.
struct SectionHead: View {
    let title: String
    var note: String? = nil
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.headline)
            if let note { Text(note).font(.footnote).foregroundStyle(.secondary) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A label with right-aligned values, for small tables.
struct StatRow: View {
    let label: String
    let values: [String]
    var colors: [Color?] = []
    var bold = false
    var header = false
    var body: some View {
        HStack(spacing: 6) {
            Text(label).frame(maxWidth: .infinity, alignment: .leading).lineLimit(1)
            ForEach(values.indices, id: \.self) { i in
                Text(values[i]).monospacedDigit().foregroundStyle(colors.indices.contains(i) ? colors[i] ?? .primary : .primary)
                    .frame(width: values.count > 3 ? 46 : 64, alignment: .trailing).lineLimit(1)
            }
        }
        .font(header ? .caption : .subheadline)
        .fontWeight(bold ? .semibold : nil)
        .foregroundStyle(header ? .secondary : .primary)
    }
}

struct LoadingView: View {
    var text = "Loading…"
    var body: some View {
        VStack(spacing: 10) { ProgressView(); Text(text).font(.footnote).foregroundStyle(.secondary) }
            .frame(maxWidth: .infinity).padding(32)
    }
}

/// Shows `content` with the league once it's loaded, or the reason it can't be.
struct WithLeague<Content: View>: View {
    @Environment(AppModel.self) private var model
    @ViewBuilder let content: (League) -> Content
    var body: some View {
        if let lg = model.league { content(lg) }
        else if model.loadError != nil || !model.hasBundle { SyncView() }
        else { LoadingView(text: "Opening the data from your Mac…") }
    }
}

/// The game's score and status line ("7:30 pm", "Q3 4:12", "Final").
@MainActor func statusLine(_ g: Game, _ model: AppModel) -> String {
    let n = model.now(g)
    if n.status == 1 { return g.start?.nzTime ?? "TBD" }
    return n.text.isEmpty ? (n.status == 3 ? "Final" : "Live") : n.text
}

func recordText(_ lg: League, _ teamId: Int) -> String {
    if let cur = lg.seasons[lg.cur]?[teamId], cur.gp > 0 { return "\(cur.w)–\(cur.l)" }
    guard let prev = lg.seasons[lg.prev]?[teamId] else { return "" }
    return "\(prev.w)–\(prev.l) last season"
}

/// A player's status on the NBA injury report: a coloured capsule, with the reason unless `compact`.
struct InjuryLabel: View {
    let note: InjuryNote
    var compact = false
    var body: some View {
        let color: Color = note.status == "Out" ? .red : note.status == "Doubtful" ? .orange : note.status == "Questionable" ? .yellow : .green
        HStack(spacing: 5) {
            Text(note.status).font(.caption2.weight(.semibold)).padding(.horizontal, 6).padding(.vertical, 1)
                .background(color.opacity(note.counts ? 0.85 : 0.25), in: .capsule).foregroundStyle(note.counts ? .white : .primary)
            if !compact && !note.reason.isEmpty && note.status != "Available" {
                Text(note.reason).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
            }
        }
    }
}
