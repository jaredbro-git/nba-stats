import SwiftUI

/// Every team by projected strength, in its conference.
struct TeamsView: View {
    var body: some View {
        WithLeague { lg in TeamsList(lg: lg) }
            .navigationTitle("Teams")
            .toolbar { SyncButton() }
    }
}

private struct TeamsList: View {
    let lg: League
    @Environment(AppModel.self) private var model

    var body: some View {
        let _ = model.generation
        let out = model.nowOut(lg)
        let nets = Dictionary(uniqueKeysWithValues: lg.teams.keys.map { ($0, lg.strength($0, out: out).net) })
        List {
            ForEach(["East", "West"], id: \.self) { conf in
                Section("\(conf)ern Conference") {
                    ForEach(lg.teams.values.filter { $0.conference == conf }.sorted { nets[$0.id]! > nets[$1.id]! }) { t in
                        NavigationLink(value: Route.team(t.id)) {
                            HStack(spacing: 12) {
                                TeamBadge(team: t, size: 36)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(t.name).font(.body.weight(.semibold))
                                    Text([recordText(lg, t.id), nextGame(t)].compactMap { $0?.isEmpty == false ? $0 : nil }.joined(separator: " · "))
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Text(signed(nets[t.id])).font(.subheadline.weight(.semibold)).monospacedDigit().foregroundStyle(tone(nets[t.id]!))
                            }
                        }
                    }
                }
            }
            Section {
                Text("Ordered by projected net rating (points per 100 possessions more than they allow), for the current roster without players marked out or listed out on the NBA injury report.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func nextGame(_ t: Team) -> String? {
        guard let g = lg.schedule.first(where: { ($0.homeId == t.id || $0.awayId == t.id) && model.now($0).status != 3 }) else { return nil }
        let home = g.homeId == t.id
        return "Next: \(home ? "vs" : "@") \(lg.teams[home ? g.awayId : g.homeId]?.abbr ?? "TBD") \(g.start?.nzDay ?? "")"
    }
}

/// A team: projected ratings, schedule with predictions, results, and the roster (mark players out).
struct TeamView: View {
    let teamId: Int
    var body: some View {
        WithLeague { lg in
            if let team = lg.teams[teamId] { TeamContent(lg: lg, team: team) } else { Text("No such team") }
        }
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct TeamContent: View {
    let lg: League
    let team: Team
    @Environment(AppModel.self) private var model
    @State private var tab = "Upcoming"

    var body: some View {
        let _ = model.generation
        let out = model.nowOut(lg)
        let all = Dictionary(uniqueKeysWithValues: lg.teams.keys.map { ($0, lg.strength($0, out: out)) })
        let s = all[team.id]!
        // League rank, higher values first (for defence, higher means fewer points allowed).
        let rank = { (v: (Strength) -> Double) -> Int in all.values.filter { v($0) > v(s) }.count + 1 }
        List {
            Section {
                HStack(spacing: 14) {
                    TeamBadge(team: team, size: 54)
                    VStack(alignment: .leading) {
                        Text(team.name).font(.title2.weight(.bold))
                        Text("\(team.conference)ern Conference · \(recordText(lg, team.id))").font(.subheadline).foregroundStyle(.secondary)
                    }
                }
                Tiles(tiles: [
                    Tile(value: one(lg.leagueOrtg + s.off), label: "Offence (pts per 100)", sub: "#\(rank { $0.off }) in the league"),
                    Tile(value: one(lg.leagueOrtg - s.def), label: "Defence (allowed per 100)", sub: "#\(rank { $0.def }) in the league"),
                    Tile(value: signed(s.net), label: "Net rating", sub: "#\(rank { $0.net }) in the league", tone: tone(s.net)),
                    Tile(value: one(lg.leaguePace + s.pace), label: "Pace", sub: "#\(rank { $0.pace }) fastest"),
                ])
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())
                Picker("Show", selection: $tab) { ForEach(["Upcoming", "Results", "Roster"], id: \.self) { Text($0) } }
                    .pickerStyle(.segmented)
            }
            .listRowSeparator(.hidden)
            switch tab {
            case "Upcoming": upcoming
            case "Results": results
            default: roster(out: model.unavailable(lg), minutes: s.minutes)
            }
        }
    }

    private var games: [Game] { lg.schedule.filter { $0.homeId == team.id || $0.awayId == team.id } }

    @ViewBuilder private var upcoming: some View {
        let list = games.filter { model.now($0).status != 3 }
        Section {
            if list.isEmpty { Text("No games left on the schedule.").foregroundStyle(.secondary) }
            ForEach(list) { g in
                let home = g.homeId == team.id
                let opp = lg.teams[home ? g.awayId : g.homeId]
                let out = model.out(for: g, lg)
                let p = lg.predict(home: g.homeId, away: g.awayId, out: out, usDate: g.usDate, neutral: g.neutral)
                let win = home ? p.homeWin : 1 - p.homeWin
                NavigationLink(value: Route.game(g.id)) {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 6) {
                                Text(home ? "vs" : "@").foregroundStyle(.secondary)
                                TeamBadge(team: opp, size: 24)
                                Text(opp?.nickname ?? "TBD").fontWeight(.semibold)
                            }
                            Text([g.start.map { "\($0.nzDay), \($0.nzTime)" }, (home ? p.home.b2b : p.away.b2b) ? "back-to-back" : nil, g.sublabel.isEmpty ? nil : g.sublabel]
                                .compactMap { $0 }.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
                            let names = out.compactMap { lg.players[$0] }.filter { $0.teamId == g.homeId || $0.teamId == g.awayId }.map(\.name)
                            if !names.isEmpty { Text("Out: \(names.sorted().joined(separator: ", "))\(lg.gameOuts[g.id] != nil ? " · set for this game" : "")").font(.caption).foregroundStyle(.secondary) }
                        }
                        Spacer()
                        VStack(alignment: .trailing) {
                            Text(pct(win)).fontWeight(.semibold).foregroundStyle(win >= 0.5 ? .green : .red)
                            Text("\(whole(home ? p.home.pts : p.away.pts))–\(whole(home ? p.away.pts : p.home.pts))").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder private var results: some View {
        let list = games.filter { model.now($0).status == 3 }.reversed()
        Section {
            if list.isEmpty { Text("No games played yet this season.").foregroundStyle(.secondary) }
            ForEach(Array(list)) { g in
                let n = model.now(g)
                let home = g.homeId == team.id
                let mine = home ? n.home : n.away, theirs = home ? n.away : n.home
                NavigationLink(value: Route.game(g.id)) {
                    HStack(spacing: 8) {
                        Text(g.start?.nzDay ?? "").foregroundStyle(.secondary).frame(width: 92, alignment: .leading)
                        Text(home ? "vs" : "@").foregroundStyle(.secondary)
                        TeamBadge(team: lg.teams[home ? g.awayId : g.homeId], size: 24)
                        Text(lg.teams[home ? g.awayId : g.homeId]?.nickname ?? "")
                        Spacer()
                        Text("\(mine > theirs ? "W" : "L") \(mine)–\(theirs)").fontWeight(.semibold).foregroundStyle(mine > theirs ? .green : .red)
                    }
                    .font(.subheadline)
                }
            }
        }
    }

    @ViewBuilder private func roster(out: Set<Int>, minutes: [(id: Int, min: Double)]) -> some View {
        let mins = Dictionary(uniqueKeysWithValues: minutes.map { ($0.id, $0.min) })
        Section {
            ForEach(lg.roster(team.id).stableSorted { (mins[$0.id] ?? 0) * 1000 + $0.mpg > (mins[$1.id] ?? 0) * 1000 + $1.mpg }) { p in
                let isOut = out.contains(p.id)
                let season = p.perGame[lg.cur] != nil ? lg.cur : lg.prev
                HStack {
                    NavigationLink(value: Route.player(p.id)) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(p.name).fontWeight(.semibold).foregroundStyle(isOut ? .secondary : .primary).strikethrough(isOut)
                            if let note = lg.injuryNotes[p.id] { InjuryLabel(note: note) }
                            Text([p.position.isEmpty ? nil : p.position, mins[p.id].map { "\(whole($0)) min" } ?? "outside the rotation",
                                  p.perGame[season].map { "\(one($0["PTS"])) pts · \(one($0["REB"])) reb · \(one($0["AST"])) ast" } ?? "no NBA stats yet",
                                  "impact \(signed(p.impact))"].compactMap { $0 }.joined(separator: " · "))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Toggle("Plays", isOn: Binding(get: { !isOut }, set: { model.setOut(lg, [p.id], out: !$0) })).labelsHidden()
                }
            }
        } footer: {
            Text("Switch a player off to leave him out of every prediction on this phone (your Mac's list comes across with each copy). Players the NBA injury report lists as Out are left out automatically until a later report clears them. To change one game only, open that game.")
        }
    }
}
