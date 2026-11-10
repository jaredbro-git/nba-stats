import SwiftUI

/// Hexagon colour for a step (-4 colder ... +4 hotter), as the Mac's shot charts.
func hexColor(_ step: Int) -> Color {
    let mid = Color(white: 0.55)
    if step == 0 { return mid }
    return mid.mix(with: step > 0 ? Color(red: 0.86, green: 0.22, blue: 0.18) : Color(red: 0.16, green: 0.45, blue: 0.86), by: Double(abs(step)) / 4)
}

/// The hexagon heat map on a half court (basket at the bottom), with tap-for-details and a zone table.
struct ShotChartView: View {
    let chart: Shots.Chart
    var defence = false
    @State private var picked: Shots.Hex?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("\(chart.fga.formatted()) shots in \(chart.games) games · \(pct(chart.pct, 1)) FG (\(signed((chart.pct - chart.league) * 100)) vs league from the same spots) · \(pct(chart.efg, 1)) eFG · \(pct(chart.threeShare)) threes")
                .font(.caption).foregroundStyle(.secondary)
            GeometryReader { geo in
                let k = geo.size.width / 500
                Canvas { ctx, size in
                    ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(Color(.secondarySystemBackground)))
                    for h in chart.hexes {
                        let path = hexPath(h.cx, h.cy, h.size, k)
                        ctx.fill(path, with: .color(hexColor(h.step)))
                        if h == picked { ctx.stroke(path, with: .color(.primary), lineWidth: 2) }
                    }
                    drawCourt(&ctx, k)
                }
                .contentShape(Rectangle())
                .onTapGesture { pos in
                    let x = pos.x / k - 250, y = Shots.yTop - pos.y / k
                    let nearest = chart.hexes.min { hypot($0.cx - x, $0.cy - y) < hypot($1.cx - x, $1.cy - y) }
                    picked = nearest.flatMap { hypot($0.cx - x, $0.cy - y) <= Shots.hexR * 1.1 ? $0 : nil }
                }
            }
            .aspectRatio(500 / 400, contentMode: .fit)
            .clipShape(.rect(cornerRadius: 14))
            HStack(spacing: 2) {
                Text(defence ? "Opponents worse" : "Colder").font(.caption2)
                ForEach(-4...4, id: \.self) { s in Rectangle().fill(hexColor(s)).frame(width: 12, height: 12) }
                Text(defence ? "better" : "hotter than league").font(.caption2)
            }
            .foregroundStyle(.secondary)
            if let h = picked {
                Text("\(h.zone): \(h.fgm)/\(h.fga) (\(pct(h.pct, 1))), league \(pct(h.league, 1)), \(signed((h.pct - h.league) * 100)) pts").font(.footnote)
            }
            StatRow(label: "Zone", values: ["Shots", "FG%", "Lg", "±"], header: true)
            ForEach(chart.zones) { z in
                HStack(spacing: 6) {
                    Rectangle().fill(hexColor(z.step)).frame(width: 10, height: 10)
                    StatRow(label: z.label, values: [pct(z.share), pct(z.pct, 1), pct(z.league, 1), signed(z.diff * 100)],
                            colors: [nil, nil, nil, abs(z.diff) > 0.01 ? ((z.diff > 0) != defence ? .green : .red) : nil])
                }
            }
        }
    }

    private func hexPath(_ cx: Double, _ cy: Double, _ r: Double, _ k: CGFloat) -> Path {
        var path = Path()
        for i in 0..<6 {
            let a = (60.0 * Double(i) - 30) * .pi / 180
            let p = CGPoint(x: (cx + r * cos(a) + 250) * k, y: (Shots.yTop - (cy + r * sin(a))) * k)
            if i == 0 { path.move(to: p) } else { path.addLine(to: p) }
        }
        path.closeSubpath()
        return path
    }

    /// Court lines in NBA coordinates (as shots.court_svg).
    private func drawCourt(_ ctx: inout GraphicsContext, _ k: CGFloat) {
        let color = Color.primary.opacity(0.55)
        func p(_ x: Double, _ y: Double) -> CGPoint { CGPoint(x: (x + 250) * k, y: (Shots.yTop - y) * k) }
        func line(_ x1: Double, _ y1: Double, _ x2: Double, _ y2: Double) {
            var path = Path(); path.move(to: p(x1, y1)); path.addLine(to: p(x2, y2)); ctx.stroke(path, with: .color(color), lineWidth: 1.5)
        }
        /// An arc in court terms: angles in degrees, counter-clockwise from the +x axis (y up).
        func arc(_ cx: Double, _ cy: Double, _ r: Double, from a0: Double, to a1: Double, dashed: Bool = false) {
            var path = Path()
            let steps = 48
            for i in 0...steps {
                let a = (a0 + (a1 - a0) * Double(i) / Double(steps)) * .pi / 180
                let pt = p(cx + r * cos(a), cy + r * sin(a))
                if i == 0 { path.move(to: pt) } else { path.addLine(to: pt) }
            }
            ctx.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: 1.5, dash: dashed ? [6, 6] : []))
        }
        line(-250, -47.5, 250, -47.5)                                         // baseline
        line(-80, -47.5, -80, 142.5); line(80, -47.5, 80, 142.5); line(-80, 142.5, 80, 142.5)   // lane
        line(-60, -47.5, -60, 142.5); line(60, -47.5, 60, 142.5)
        line(-30, -7.5, 30, -7.5)                                             // backboard
        arc(0, 142.5, 60, from: 0, to: 180)                                   // free-throw circle, top half
        arc(0, 142.5, 60, from: 180, to: 360, dashed: true)
        arc(0, 0, 40, from: 0, to: 180)                                       // restricted area
        arc(0, 0, 7.5, from: 0, to: 360)                                      // rim
        let cornerY = (237.5 * 237.5 - 220 * 220).squareRoot()
        line(-220, -47.5, -220, cornerY); line(220, -47.5, 220, cornerY)
        let angle = atan2(cornerY, 220) * 180 / .pi
        arc(0, 0, 237.5, from: angle, to: 180 - angle)                        // three-point arc
    }
}

/// The expected outcome of one player guarding another (the Mac app's matchup popup).
struct EstimateSheet: View {
    let lg: League
    let shooter, defender: Int
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let s = lg.players[shooter], d = lg.players[defender]
        let est = lg.matchups.estimate(shooter, defender)
        let pair = lg.matchups.pair(shooter, defender)
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text(s?.name ?? "\(shooter)").font(.title3.weight(.bold))
                    Text("guarded by").font(.footnote).foregroundStyle(.secondary)
                    Text(d?.name ?? "\(defender)").font(.title3.weight(.bold))
                    Text("\(heightText(s?.height)) \(s?.position ?? "")  vs  \(heightText(d?.height)) \(d?.position ?? "")").font(.footnote).foregroundStyle(.secondary)
                    if let est {
                        if pair == nil {
                            Text("This matchup has never happened (tracked since \(lg.matchups.firstSeason)). The expected outcome is estimated from each player's numbers.")
                                .font(.footnote).padding(12).glassEffect(.regular, in: .rect(cornerRadius: 14))
                        }
                        Tiles(tiles: [
                            Tile(value: one(est.pts100), label: "Points per 100 possessions", sub: "\(signed(est.effect100)) vs his usual \(one(est.basePts100))",
                                 tone: est.effect100 < -0.5 ? .green : est.effect100 > 0.5 ? .red : .primary),
                            Tile(value: pct(est.fg, 1), label: "FG%", sub: "usually \(pct(est.baseFg, 1))"),
                            Tile(value: pct(est.fg3, 1), label: "3P%", sub: "usually \(pct(est.baseFg3, 1))"),
                        ])
                        let mpg = (s?.mpg ?? 0) > 0 ? s!.mpg : 30
                        let guarded = lg.matchups.primaryShare * mpg / 48 * lg.leaguePace
                        let g = guarded / 100
                        Text("In a game where \(d?.name ?? "he") is his main defender (about \(Int((lg.matchups.primaryShare * 100).rounded()))% of his possessions, ~\(whole(guarded)) possessions): \(one(est.pts100 * g)) pts on \(one(est.fga100 * g * est.fg))/\(one(est.fga100 * g)) FG, \(one(est.fg3a100 * g * est.fg3))/\(one(est.fg3a100 * g)) 3P.")
                        if let pair {
                            SectionHead(title: "Head to head")
                            Text("\(pair.fgm)/\(pair.fga) FG, \(pair.fg3m)/\(pair.fg3a) 3P, \(pair.pts) pts on \(whole(pair.poss)) possessions in \(pair.gp) games (\(pair.poss > 0 ? whole(100 * Double(pair.pts) / pair.poss) : "–") per 100). \(est.confidence) confidence.")
                                .font(.footnote)
                        }
                        SectionHead(title: "How it's estimated")
                        StatRow(label: "His usual scoring", values: ["\(one(est.basePts100)) per 100"])
                        StatRow(label: "\(d?.name ?? "Defender")'s defensive rating", values: [signed(est.rating100)],
                                colors: [est.rating100 < -0.5 ? .green : est.rating100 > 0.5 ? .red : nil])
                        if let c = est.closeFg {
                            Text("Shooters hit \(signed(c * 100)) FG% points vs normal with him closest\(est.closeFg3.map { " (\(signed($0 * 100)) on threes)" } ?? "").")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        StatRow(label: "Height difference", values: [est.size.map { "\(signed($0, 0))″" } ?? "–"])
                        Text("Height barely matters once the defender's own ability is counted.").font(.caption).foregroundStyle(.secondary)
                        StatRow(label: "Head to head", values: [est.h2h100.map { signed($0) } ?? "–"])
                        Text(est.h2h100 != nil ? "Counted at \(Int((est.h2hWeight * 100).rounded()))% weight, more as their history grows." : "None: the estimate uses the rating and height only.")
                            .font(.caption).foregroundStyle(.secondary)
                    } else {
                        Text("Not enough tracked possessions for \(s?.name ?? "him") to estimate a matchup.")
                    }
                }
                .padding()
            }
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .presentationDetents([.medium, .large])
    }
}
