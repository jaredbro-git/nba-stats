import SwiftUI

/// The season simulator and the trade machine.
struct WhatIfView: View {
    @State private var page = "Season"
    var body: some View {
        WithLeague { lg in
            VStack(spacing: 0) {
                Picker("", selection: $page) { Text("Season sim").tag("Season"); Text("Trade machine").tag("Trades") }
                    .pickerStyle(.segmented).padding(.horizontal).padding(.bottom, 6)
                if page == "Season" { SimulatorContent(lg: lg) } else { TradesContent(lg: lg) }
            }
            .background(Color(.systemGroupedBackground))
        }
        .navigationTitle("What if")
        .toolbar { SyncButton() }
    }
}

// MARK: Season simulator

private let missChoices: [(Int?, String)] = [(5, "next 5 games"), (10, "next 10 games"), (20, "next 20 games"), (41, "next 41 games"), (nil, "rest of season")]
private let savedChoices: [(String, String)] = [("0", "Play every game"), ("5", "Miss their next 5 games"), ("10", "Miss their next 10 games"),
                                                ("20", "Miss their next 20 games"), ("rest", "Miss the rest of the season")]

private struct SimulatorContent: View {
    let lg: League
    @Environment(AppModel.self) private var model
    @State private var saved = "10"
    @State private var scenario: [Int: Int?] = [:]
    @State private var order: [Int] = []
    @State private var result: SimResult?
    @State private var expanded: Int?
    @State private var search = ""

    private var inputs: (missing: [Int: Int?], gameOuts: [String: Set<Int>]) {
        let games: Int? = saved == "rest" ? nil : Int(saved) ?? 10
        var m: [Int: Int?] = [:], outs = lg.gameOuts
        if saved != "0" { (m, outs) = model.simInputs(lg, games: games) }
        for (k, v) in scenario { m[k] = v }
        return (m, outs)
    }

    var body: some View {
        List {
            Section {
                Text(result.map { "The rest of the season, the play-in and the playoffs, played \($0.sims.formatted()) times with the game model (\($0.gamesLeft) regular-season games left)." }
                     ?? "Playing the rest of the season 10,000 times…").font(.footnote).foregroundStyle(.secondary)
            }
            Section("What if…") {
                Picker("Out now: your list + injury report (\(model.nowOut(lg).count))", selection: $saved) { ForEach(savedChoices, id: \.0) { Text($0.1).tag($0.0) } }
                ForEach(order, id: \.self) { pid in
                    HStack {
                        NavigationLink(value: Route.player(pid)) {
                            VStack(alignment: .leading) {
                                Text(lg.nameOf(pid)).fontWeight(.semibold)
                                Text(lg.players[pid]?.teamId.flatMap { lg.teams[$0]?.abbr } ?? "").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        Menu("misses " + (missChoices.first { $0.0 == (scenario[pid] ?? nil) }?.1 ?? "")) {
                            ForEach(missChoices, id: \.1) { c in Button("misses " + c.1) { scenario[pid] = .some(c.0) } }
                        }
                        .font(.footnote)
                    }
                    .swipeActions { Button("Remove", role: .destructive) { scenario[pid] = nil; order.removeAll { $0 == pid } } }
                }
                TextField("Add a player who misses games", text: $search).autocorrectionDisabled()
                ForEach(search.count >= 2 ? Array(lg.search(search, limit: 30).filter { lg.players[$0.id]?.teamId != nil }.prefix(6)) : [], id: \.id) { m in
                    Button {
                        if scenario[m.id] == nil { scenario[m.id] = .some(10); order.append(m.id) }
                        search = ""
                    } label: { HStack { Text(m.name); Spacer(); Text(lg.players[m.id]?.teamId.flatMap { lg.teams[$0]?.abbr } ?? "").foregroundStyle(.secondary) } }
                }
                if !scenario.isEmpty { Button("Clear what-ifs") { scenario = [:]; order = [] } }
            }
            if let r = result {
                Section {
                    Tiles(tiles: r.teams.sorted { $0.title > $1.title }.prefix(4).map { Tile(value: pct($0.title, 1), label: $0.team.nickname, sub: "title · \(whole($0.wins)) wins") })
                }
                .listRowBackground(Color.clear).listRowInsets(EdgeInsets())
                ForEach(["East", "West"], id: \.self) { conf in
                    Section {
                        StatRow(label: "Team", values: ["Proj.", "Playoffs", "Title"], header: true)
                        let teams = r.teams.filter { $0.team.conference == conf }.sorted { $0.wins > $1.wins }
                        ForEach(Array(teams.enumerated()), id: \.element.id) { i, t in
                            Button { expanded = expanded == t.id ? nil : t.id } label: {
                                VStack(alignment: .leading, spacing: 6) {
                                    HStack(spacing: 8) {
                                        TeamBadge(team: t.team, size: 24)
                                        StatRow(label: t.team.nickname, values: ["\(whole(t.wins))–\(whole(t.losses))", odds(t.playoffs), odds(t.title)])
                                    }
                                    if expanded == t.id { detail(t) }
                                }
                            }
                            .buttonStyle(.plain)
                            .listRowSeparator(i == 5 || i == 9 ? .visible : .hidden, edges: .bottom)
                            .listRowSeparatorTint(.primary)
                        }
                    } header: { Text("\(conf)ern Conference") } footer: { Text("Tap a team for its full odds. Lines mark 6th (playoffs) and 10th (play-in).") }
                }
                Section {
                    Text("Every remaining game gets a win chance from the game model, with players out for the games they miss. Each simulated season also draws every team's true strength from a spread of ±\(String(format: "%.1f", r.teamSd)) points around its projection, so long-shot runs happen about as often as in reality. Top six make the playoffs; 7–10 go to the play-in; series are best of seven. Players out for the rest of the season also miss the playoffs.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else {
                LoadingView(text: "Simulating 10,000 seasons…")
            }
        }
        .task(id: "\(saved)|\(scenario.map { "\($0.key):\(String(describing: $0.value))" }.sorted())|\(model.generation)") {
            result = nil
            let lg = lg, (missing, outs) = inputs
            result = await Task.detached(priority: .userInitiated) { Simulator.run(lg, missing: missing, gameOuts: outs) }.value
        }
    }

    private func odds(_ v: Double) -> String { v >= 0.995 ? ">99%" : v == 0 ? "–" : v < 0.005 ? "<1%" : pct(v) }

    private func detail(_ t: SimTeam) -> some View {
        VStack(spacing: 3) {
            StatRow(label: "Now", values: ["\(t.record.w)–\(t.record.l)"])
            StatRow(label: "80% range", values: ["\(t.low)–\(t.high) wins"])
            ForEach([("#1 seed", t.seed1), ("Top 6", t.top6), ("Play-in", t.playin), ("Make playoffs", t.playoffs), ("2nd round", t.round2),
                     ("Conference finals", t.confFinals), ("Finals", t.finals), ("Title", t.title)], id: \.0) { StatRow(label: $0.0, values: [odds($0.1)]) }
            NavigationLink("Open \(t.team.nickname)", value: Route.team(t.id)).font(.footnote)
        }
        .font(.footnote)
        .padding(.leading, 32)
    }
}

// MARK: Trade machine

private struct TradeRating { let off, def, net: Double; let rank: Int }
private struct TradeSide: Identifiable {
    let team: Team
    let before, after: TradeRating
    let simBefore, simAfter: SimTeam
    let gets, sends: [Player]
    let rotation: [(id: Int, name: String, before: Double, after: Double)]
    var id: Int { team.id }
}

private func ratings(_ lg: League) -> [Int: TradeRating] {
    let all = Dictionary(uniqueKeysWithValues: lg.teams.keys.map { ($0, lg.strength($0, out: [])) })
    let ranked = all.sorted { $0.value.net > $1.value.net }.map(\.key)
    return all.mapValues { s in s }.reduce(into: [:]) { out, kv in
        out[kv.key] = TradeRating(off: lg.leagueOrtg + kv.value.off, def: lg.leagueOrtg - kv.value.def, net: kv.value.net, rank: (ranked.firstIndex(of: kv.key) ?? 0) + 1)
    }
}

private struct TradesContent: View {
    let lg: League
    @Environment(AppModel.self) private var model
    @State private var a = "LAL"
    @State private var b = "OKC"
    @State private var sending: Set<Int> = []
    @State private var run: Set<Int> = []
    @State private var sides: [TradeSide]?
    @State private var running = false

    var body: some View {
        let sorted = lg.teams.values.sorted { $0.name < $1.name }
        let ta = lg.byAbbr[a] ?? sorted[0]
        let tb = lg.byAbbr[b].flatMap { $0 == ta ? nil : $0 } ?? sorted.first { $0 != ta }!
        List {
            Section {
                Text("Tick the players each team sends. Both teams' ratings, rotations and season odds are recalculated with the trade. No salary-cap check: the NBA stats data doesn't include contracts.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            ForEach([ta, tb]) { team in
                let other = team == ta ? tb : ta
                Section {
                    Picker(selection: Binding(get: { team.abbr }, set: { v in if team == ta { a = v } else { b = v }; sending = []; run = []; sides = nil })) {
                        ForEach(sorted) { Text($0.name).tag($0.abbr) }
                    } label: { HStack { TeamBadge(team: team, size: 28); Text("Team") } }
                    ForEach(lg.roster(team.id).stableSorted { $0.mpg > $1.mpg }) { p in
                        Button {
                            if sending.contains(p.id) { sending.remove(p.id) } else { sending.insert(p.id) }
                        } label: {
                            HStack {
                                Image(systemName: sending.contains(p.id) ? "checkmark.circle.fill" : "circle").foregroundStyle(sending.contains(p.id) ? Color.accentColor : .secondary)
                                VStack(alignment: .leading) {
                                    Text(p.name)
                                    Text("\(p.position.isEmpty ? "–" : p.position) · \(whole(p.mpg)) min · impact \(signed(p.impact))").font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                    }
                } header: { Text("Sends to the \(other.nickname)") }
            }
            Section {
                HStack {
                    Button(running ? "Running…" : "Run trade") { run = sending }.buttonStyle(.glassProminent).disabled(sending.isEmpty || running)
                    if !sending.isEmpty { Button("Clear") { sending = []; run = []; sides = nil }.buttonStyle(.glass) }
                }
            }
            .listRowBackground(Color.clear)
            if let sides {
                ForEach(sides) { s in sideResult(s) }
                Section {
                    Text("Ratings keep each team's starting point and count the traded players like marking a player out (or in): incoming players take minutes in the rotation and the team's rating moves by half of each player's estimated impact times his change in minutes (half is what predicted last season's games best). Season odds come from 10,000 simulated seasons, with players on your unavailable list or out on the NBA injury report missing their next 10 games.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else if running { LoadingView(text: "Re-rating both teams and simulating the season…") }
        }
        .task(id: "\(a)|\(b)|\(run.sorted())") {
            sides = nil
            var moves: [Int: Int] = [:]
            for pid in run { if let t = lg.players[pid]?.teamId { if t == ta.id { moves[pid] = tb.id } else if t == tb.id { moves[pid] = ta.id } } }
            guard !moves.isEmpty else { return }
            running = true
            let lg = lg, (missing, outs) = model.simInputs(lg, games: 10), pair = [ta, tb]
            sides = await Task.detached(priority: .userInitiated) { () -> [TradeSide]? in
                guard let after = try? lg.withTrade(moves) else { return nil }
                let sims = (Simulator.run(lg, missing: missing, gameOuts: outs), Simulator.run(after, missing: missing, gameOuts: outs))
                let r = (ratings(lg), ratings(after))
                return pair.map { t in
                    let rb = Dictionary(uniqueKeysWithValues: lg.rotation(t.id, out: []).map { ($0.id, $0.min) })
                    let ra = Dictionary(uniqueKeysWithValues: after.rotation(t.id, out: []).map { ($0.id, $0.min) })
                    let ids = Set(rb.keys).union(ra.keys).sorted { max(rb[$0] ?? 0, ra[$0] ?? 0) > max(rb[$1] ?? 0, ra[$1] ?? 0) }
                    return TradeSide(team: t, before: r.0[t.id]!, after: r.1[t.id]!,
                                     simBefore: sims.0.teams.first { $0.team.id == t.id }!, simAfter: sims.1.teams.first { $0.team.id == t.id }!,
                                     gets: moves.filter { $0.value == t.id }.keys.compactMap { lg.players[$0] },
                                     sends: moves.filter { $0.value != t.id }.keys.compactMap { lg.players[$0] },
                                     rotation: ids.map { ($0, lg.nameOf($0), rb[$0] ?? 0, ra[$0] ?? 0) })
                }
            }.value
            running = false
        }
    }

    private func sideResult(_ s: TradeSide) -> some View {
        func change(_ good: Double, _ text: String) -> (String, Color?) { (text, abs(good) > 0.05 ? (good > 0 ? .green : .red) : nil) }
        let rows: [(String, String, String, (String, Color?))] = [
            ("Net rating", "\(signed(s.before.net)) #\(s.before.rank)", "\(signed(s.after.net)) #\(s.after.rank)", change(s.after.net - s.before.net, signed(s.after.net - s.before.net))),
            ("Offence", one(s.before.off), one(s.after.off), change(s.after.off - s.before.off, signed(s.after.off - s.before.off))),
            ("Defence", one(s.before.def), one(s.after.def), change(s.before.def - s.after.def, signed(s.after.def - s.before.def))),
            ("Record", "\(whole(s.simBefore.wins))–\(whole(s.simBefore.losses))", "\(whole(s.simAfter.wins))–\(whole(s.simAfter.losses))",
             change(s.simAfter.wins - s.simBefore.wins, signed(s.simAfter.wins - s.simBefore.wins) + " W")),
            ("Playoffs", pct(s.simBefore.playoffs), pct(s.simAfter.playoffs), change((s.simAfter.playoffs - s.simBefore.playoffs) * 10, signed(100 * (s.simAfter.playoffs - s.simBefore.playoffs), 0) + " pts")),
            ("Finals", pct(s.simBefore.finals), pct(s.simAfter.finals), change((s.simAfter.finals - s.simBefore.finals) * 10, signed(100 * (s.simAfter.finals - s.simBefore.finals), 0) + " pts")),
            ("Title", pct(s.simBefore.title, 1), pct(s.simAfter.title, 1), change((s.simAfter.title - s.simBefore.title) * 10, signed(100 * (s.simAfter.title - s.simBefore.title), 0) + " pts")),
        ]
        return Section {
            if !s.gets.isEmpty { Text("Gets " + s.gets.map(\.name).joined(separator: ", ")) }
            if !s.sends.isEmpty { Text("Sends " + s.sends.map(\.name).joined(separator: ", ")).foregroundStyle(.secondary) }
            StatRow(label: "", values: ["Before", "After", "Change"], header: true)
            ForEach(rows, id: \.0) { r in StatRow(label: r.0, values: [r.1, r.2, r.3.0], colors: [nil, nil, r.3.1]) }
            Text("Rotation · expected minutes").font(.subheadline.weight(.semibold))
            ForEach(s.rotation, id: \.id) { r in
                NavigationLink(value: Route.player(r.id)) {
                    StatRow(label: r.name, values: [r.before > 0 ? whole(r.before) : "–", r.after > 0 ? whole(r.after) : "–"],
                            colors: [r.before == 0 && r.after > 0 ? .green : r.before > 0 && r.after == 0 ? .red : nil])
                }
            }
        } header: { HStack { TeamBadge(team: s.team, size: 22); Text(s.team.name) } }
    }
}
