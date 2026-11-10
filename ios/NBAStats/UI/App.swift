import SwiftUI

@main
struct NBAStatsApp: App {
    @State private var model = AppModel.shared
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .task { await model.load() }
                .task(id: phase) {
                    if phase == .background { Reminders.scheduleRefresh() }
                    guard phase == .active else { return }
                    // While the app is open: a fresh copy from the Mac when due, then keeping up by itself (scores every
                    // minute while a game is on; results, the injury report and picks as they come).
                    await MacLink.syncIfDue()
                    while !Task.isCancelled {
                        await model.update()
                        try? await Task.sleep(for: .seconds(model.anyLive ? 60 : 300))
                    }
                }
        }
        .backgroundTask(.appRefresh(Reminders.refreshTask)) { await AppModel.shared.backgroundUpdate() }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model
    // Launch options for testing: -startTab Players, -route game:0022600145 (or team:<id>, player:<id>).
    @State private var tab = UserDefaults.standard.string(forKey: "startTab") ?? "Today"
    @State private var paths: [String: NavigationPath] = RootView.initialPaths()

    private static func initialPaths() -> [String: NavigationPath] {
        let tab = UserDefaults.standard.string(forKey: "startTab") ?? "Today"
        guard let spec = UserDefaults.standard.string(forKey: "route") else { return [:] }
        let parts = spec.split(separator: ":", maxSplits: 1).map(String.init)
        guard parts.count == 2 else { return [:] }
        var path = NavigationPath()
        switch parts[0] {
        case "game": path.append(Route.game(parts[1]))
        case "team": if let id = Int(parts[1]) { path.append(Route.team(id)) }
        case "player": if let id = Int(parts[1]) { path.append(Route.player(id)) }
        default: break
        }
        return [tab: path]
    }

    private func stack<Content: View>(_ name: String, @ViewBuilder _ content: () -> Content) -> some View {
        NavigationStack(path: Binding(get: { paths[name] ?? NavigationPath() }, set: { paths[name] = $0 })) { content().appDestinations() }
    }

    var body: some View {
        TabView(selection: $tab) {
            Tab("Today", systemImage: "calendar", value: "Today") { stack("Today") { TodayView() } }
            Tab("Teams", systemImage: "shield.lefthalf.filled", value: "Teams") { stack("Teams") { TeamsView() } }
            Tab("Players", systemImage: "person.2", value: "Players") { stack("Players") { PlayersView() } }
            Tab("Tracker", systemImage: "checkmark.seal", value: "Tracker") { stack("Tracker") { TrackerView() } }
            Tab("What If", systemImage: "arrow.left.arrow.right", value: "What If") { stack("What If") { WhatIfView() } }
        }
        .overlay(alignment: .top) {
            if let status = model.syncStatus {
                Label(status, systemImage: "arrow.triangle.2.circlepath")
                    .font(.footnote).padding(.horizontal, 14).padding(.vertical, 8)
                    .glassEffect(.regular, in: .capsule)
                    .padding(.top, 4)
            }
        }
    }
}

/// A sync button for every page's toolbar.
struct SyncButton: View {
    @State private var showing = false
    var body: some View {
        Button { showing = true } label: { Image(systemName: "arrow.triangle.2.circlepath") }
            .accessibilityLabel("Sync with your Mac")
            .sheet(isPresented: $showing) { NavigationStack { SyncView().navigationTitle("Sync & updates").toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { showing = false } } } } }
    }
}
