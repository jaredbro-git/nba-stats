import SwiftUI

/// Pairing with the Mac and copying its data (the Mac's Phone page shows the pairing code).
struct SyncView: View {
    @Environment(AppModel.self) private var model
    @State private var macs: [MacLink.Mac] = []
    @State private var searching = false
    @State private var asked: MacLink.Mac?
    @State private var code = ""
    @State private var message: String?
    @State private var busy = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let err = model.loadError { Text(err).padding(12).frame(maxWidth: .infinity, alignment: .leading).background(.orange.opacity(0.18), in: .rect(cornerRadius: 14)) }
                if let paired = MacLink.paired {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Paired with \(paired.name)").font(.headline)
                        Text("The phone copies the Mac's data when the app opens (every 30 minutes at most), while NBA Stats is open on the Mac and both are on the same Wi-Fi, and sends the Mac the picks it saved. In between, it keeps up by itself (below).")
                            .font(.footnote).foregroundStyle(.secondary)
                        if let last = MacLink.lastCopy { Text("Last copied \(last.formatted(.relative(presentation: .named))).").font(.footnote) }
                        HStack {
                            Button(busy ? "Copying…" : "Copy now") { Task { busy = true; message = await MacLink.sync(); busy = false } }
                                .buttonStyle(.glassProminent).disabled(busy)
                            Button("Unpair", role: .destructive) { MacLink.unpair(); message = nil; macs = [] }.buttonStyle(.glass)
                        }
                    }
                    .card()
                    if let lg = model.league {
                        Text("Data from the Mac: \(lg.players.count) players, \(lg.games.count) games, \(lg.cur) season.").font(.footnote).foregroundStyle(.secondary)
                    }
                } else {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Pair with your Mac").font(.headline)
                        Text("Open NBA Stats on your Mac and go to its Phone page. Then find it here (same Wi-Fi), and type the 6-digit code it shows.")
                            .font(.footnote).foregroundStyle(.secondary)
                        if let mac = asked {
                            TextField("6-digit code", text: $code).keyboardType(.numberPad).textFieldStyle(.roundedBorder).font(.title3.monospacedDigit())
                            Button("Pair with \(mac.name)") {
                                Task {
                                    busy = true
                                    do {
                                        try await MacLink.confirm(mac, code: code)
                                        message = await MacLink.sync()
                                        asked = nil
                                    } catch { message = error.localizedDescription }
                                    busy = false
                                }
                            }
                            .buttonStyle(.glassProminent).disabled(code.count != 6 || busy)
                        } else {
                            Button(searching ? "Looking…" : "Find my Mac") {
                                Task { searching = true; macs = await MacLink.find(); searching = false; if macs.isEmpty { message = "No Mac found. Check NBA Stats is open on it and you're on the same Wi-Fi." } }
                            }
                            .buttonStyle(.glassProminent).disabled(searching)
                            ForEach(macs, id: \.self) { mac in
                                Button {
                                    Task {
                                        do { try await MacLink.askToPair(mac); asked = mac; message = "Now type the code shown on the Mac's Phone page." }
                                        catch { message = error.localizedDescription }
                                    }
                                } label: { Label(mac.name, systemImage: "desktopcomputer") }
                                .buttonStyle(.glass)
                            }
                        }
                    }
                    .card()
                }
                if let message = message ?? model.syncMessage { Text(message).font(.footnote) }
                OnPhoneCard()
                RemindersCard()
            }
            .padding()
        }
        .background(Color(.systemGroupedBackground))
    }
}

/// What the phone keeps up with by itself between copies.
private struct OnPhoneCard: View {
    @Environment(AppModel.self) private var model
    @State private var refreshOff = false
    @State private var lowPower = ProcessInfo.processInfo.isLowPowerModeEnabled

    var body: some View {
        let _ = model.generation
        VStack(alignment: .leading, spacing: 6) {
            Text("Keeping up without the Mac").font(.headline)
            Text("Anywhere with internet, the phone gets scores and results (and redoes team ratings with them), reads the NBA injury report, and saves its own picks until tip-off. It does this while the app is open, and now and then in the background when iOS allows it.")
                .font(.footnote).foregroundStyle(.secondary)
            if let lg = model.league {
                if let day = lg.latestResult, lg.ratingsRedone { row("Results", "up to \(day), team ratings redone on this iPhone") }
                else { row("Results", "as of your Mac's last copy") }
                if let t = lg.injuryPublished { row("Injury report", "\(t.nzDay), \(t.nzTime) · \(model.injuriesOnPhone ? "read by this iPhone" : "from your Mac")") }
            }
            if let t = model.lastUpdate { row("Last update", t.formatted(.relative(presentation: .named))) }
            if let e = model.updateError { Text(e).font(.caption).foregroundStyle(.orange) }
            if refreshOff { Text("Background App Refresh is off for NBA Stats (Settings > General > Background App Refresh), so it only updates while open.").font(.caption).foregroundStyle(.orange) }
            if lowPower { Text("Low Power Mode is on, which pauses background updates.").font(.caption).foregroundStyle(.orange) }
            Button(model.updating ? "Updating…" : "Update now") { Task { await model.update(force: true) } }
                .buttonStyle(.glass).disabled(model.updating)
        }
        .card()
        .task { refreshOff = UIApplication.shared.backgroundRefreshStatus != .available }
    }

    private func row(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) { Text(label).foregroundStyle(.secondary); Spacer(); Text(value).multilineTextAlignment(.trailing) }.font(.footnote)
    }
}

/// A reminder a few minutes before each start time, so a tap updates the picks with the latest injury report.
private struct RemindersCard: View {
    @Environment(AppModel.self) private var model
    @State private var mode = Reminders.mode
    @State private var teams = Reminders.teams
    @State private var minutes = Reminders.minutes
    @State private var denied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Tip-off reminders").font(.headline)
            Text("A notification before each start time. Tapping it opens the app, which reads the latest injury report and updates the picks before they lock.")
                .font(.footnote).foregroundStyle(.secondary)
            Picker("Remind me", selection: $mode) { ForEach(Reminders.Mode.allCases) { Text($0.label).tag($0) } }.pickerStyle(.segmented)
            if mode != .off {
                Stepper("\(minutes) minutes before", value: $minutes, in: 5...60, step: 5)
            }
            if mode == .teams, let lg = model.league {
                DisclosureGroup("\(teams.count) team\(teams.count == 1 ? "" : "s") chosen") {
                    ForEach(lg.teams.values.sorted { $0.name < $1.name }) { t in
                        Toggle(t.name, isOn: Binding(get: { teams.contains(t.id) }, set: { on in if on { teams.insert(t.id) } else { teams.remove(t.id) } }))
                    }
                }
            }
            if denied { Text("Notifications are off for NBA Stats in Settings, so reminders can't show.").font(.caption).foregroundStyle(.orange) }
        }
        .card()
        .onChange(of: mode) { _, m in
            Reminders.mode = m
            Task {
                if m != .off { denied = !(await Reminders.askPermission()) }
                await apply()
            }
        }
        .onChange(of: minutes) { _, m in Reminders.minutes = m; Task { await apply() } }
        .onChange(of: teams) { _, t in Reminders.teams = t; Task { await apply() } }
    }

    private func apply() async {
        if let lg = model.league { await Reminders.schedule(lg, model: model) }
    }
}
