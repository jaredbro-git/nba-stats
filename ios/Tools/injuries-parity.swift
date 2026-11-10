// Reads injury report PDFs with the iPhone app's reader (Injuries.swift) and prints what it finds as JSON, for
// Tools/injuries-parity.sh to compare with the Mac's (app/injuries.py).
import Foundation

let args = CommandLine.arguments
guard args.count >= 3, let db = Db(path: args[1]), let lg = try? League(db: db) else { print("usage: injuries-parity <bundle.db> <pdf>..."); exit(2) }
var out: [String: Any] = [:]
for path in args.dropFirst(2) {
    guard let data = FileManager.default.contents(atPath: path) else { continue }
    let rows = Injuries.parse(data)
    let (games, players, unmatched) = Injuries.match(lg, rows)
    out[(path as NSString).lastPathComponent] = [
        "rows": rows.map { ["date": $0.date ?? NSNull(), "matchup": $0.matchup ?? NSNull(), "team": $0.team ?? NSNull(),
                            "player": $0.player, "status": $0.status, "reason": $0.reason] as [String: Any] },
        "games": games, "players": players.mapValues { ["status": $0.status, "reason": $0.reason, "team": $0.team, "game_id": $0.game_id ?? NSNull()] as [String: Any] },
        "unmatched": unmatched.count,
    ]
}
print(String(decoding: try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]), as: UTF8.self))
