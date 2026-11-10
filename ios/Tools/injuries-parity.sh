#!/bin/sh
# Checks the iPhone app's injury report reader (Injuries.swift) against the Mac's (app/injuries.py) on real reports.
# Usage, from the project folder with the app's data:
#   DATA_DIR="$HOME/Library/Application Support/NBA Stats" ios/Tools/injuries-parity.sh bundle.db report.pdf...
set -e
root="$(cd "$(dirname "$0")/../.." && pwd)"
out="${TMPDIR:-/tmp}/nbastats-injuries-parity"
mkdir -p "$out"
cp "$root/ios/Tools/injuries-parity.swift" "$out/main.swift"
cd "$root/ios"
xcrun swiftc -O -o "$out/injuries-parity" "$out/main.swift" NBAStats/Data/Db.swift NBAStats/Data/League.swift NBAStats/Data/Matchups.swift \
  NBAStats/Data/Ratings.swift NBAStats/Data/Injuries.swift
"$out/injuries-parity" "$@" > "$out/swift.json"
shift
cd "$root"
PYTHONPATH=. .venv/bin/python - "$out/swift.json" "$@" <<'PY'
import json, sys
from pathlib import Path
from app import injuries, model
swift = json.loads(Path(sys.argv[1]).read_text())
lg = model.league()
bad = checked = 0
for path in sys.argv[2:]:
    name = Path(path).name
    rows = injuries.parse(Path(path).read_bytes())
    games, players, unmatched = injuries._match(lg, rows)
    s = swift[name]
    want = [{k: r[k] for k in ("date", "matchup", "team", "player", "status", "reason")} for r in rows]
    checked += 1
    if want != s["rows"]:
        bad += 1
        print(f"{name}: rows differ ({len(want)} vs {len(s['rows'])})")
        for a, b in zip(want, s["rows"]):
            if a != b:
                print("  mac  ", a); print("  phone", b); break
    if games != s["games"] or {p: {k: e[k] for k in ("status", "reason", "team", "game_id")} for p, e in players.items()} != s["players"] \
            or len(unmatched) != s["unmatched"]:
        bad += 1
        print(f"{name}: matching differs")
    else:
        print(f"{name}: {len(rows)} rows, {len(players)} players match")
print("PASS" if not bad else f"FAILED {bad}", f"({checked} reports)")
sys.exit(1 if bad else 0)
PY
