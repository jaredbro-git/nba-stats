#!/bin/sh
# Compiles the iPhone app's model (NBAStats/Data, minus the iPhone-only files) with Tools/parity.swift for this Mac
# and checks it against Python's answers. Usage: Tools/parity.sh bundle.db expected.json
set -e
cd "$(dirname "$0")/.."
out="${TMPDIR:-/tmp}/nbastats-parity"
mkdir -p "$out"
cp Tools/parity.swift "$out/main.swift"
xcrun swiftc -O -o "$out/parity" "$out/main.swift" NBAStats/Data/Db.swift NBAStats/Data/League.swift NBAStats/Data/Matchups.swift \
  NBAStats/Data/Simulator.swift NBAStats/Data/Tracker.swift NBAStats/Data/Shots.swift NBAStats/Data/Ratings.swift
"$out/parity" "$1" "$2"
