#!/usr/bin/env bash
# Build the Mac app (Apple Silicon).
#
#   ./build-app.sh            build dist/NBA Stats.app
#   ./build-app.sh install    build, then replace /Applications/NBA Stats.app and open it
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="NBA Stats"
PYTHON="$( [ -x /opt/homebrew/bin/python3 ] && echo /opt/homebrew/bin/python3 || command -v python3)"
VERSION="$(date +%Y%m%d%H%M)"

VENV=".venv-build"
if [ ! -d "$VENV" ]; then
  echo "Setting up the build environment…"
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
fi
"$VENV/bin/pip" install --quiet -r requirements-app.txt

mkdir -p build
"$VENV/bin/python" build_tools/make_icon.py build/icon.icns

echo "Building ${APP_NAME}…"
"$VENV/bin/pyinstaller" --noconfirm --log-level WARN --windowed \
  --name "$APP_NAME" \
  --icon "$PWD/build/icon.icns" \
  --osx-bundle-identifier "nz.jaredbro.nbastats" \
  --target-arch arm64 \
  --add-data "$PWD/app/templates:app/templates" \
  --add-data "$PWD/app/static:app/static" \
  --collect-submodules uvicorn \
  --collect-submodules nba_api \
  --collect-submodules zeroconf \
  --distpath dist --workpath build/pyinstaller --specpath build \
  desktop.py

APP="dist/$APP_NAME.app"
PLIST="$APP/Contents/Info.plist"
for key in CFBundleShortVersionString CFBundleVersion; do
  /usr/libexec/PlistBuddy -c "Set :$key $VERSION" "$PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :$key string $VERSION" "$PLIST"
done
# The phone finds this Mac with Bonjour and connects over the local network.
/usr/libexec/PlistBuddy -c "Delete :NSBonjourServices" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Delete :NSLocalNetworkUsageDescription" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy \
  -c "Add :NSLocalNetworkUsageDescription string NBA Stats lets the NBA Stats app on your phone copy its data over Wi-Fi." \
  -c "Add :NSBonjourServices array" -c "Add :NSBonjourServices:0 string _nbastats._tcp" "$PLIST"
# A fixed signing identity (a self-signed certificate in your keychain), so macOS keeps the app's
# local network and firewall permissions across rebuilds. Ad hoc signatures lose them each build.
build_tools/make_signing_identity.sh >/dev/null
codesign --force --deep --sign "NBA Stats Signing" "$APP"
codesign --verify --deep --strict "$APP"
echo "Built $APP (version $VERSION)"

if [ "${1:-}" = "install" ]; then
  osascript -e "quit app \"$APP_NAME\"" 2>/dev/null || true
  for _ in $(seq 1 20); do pgrep -f "/Applications/$APP_NAME.app/" >/dev/null || break; sleep 0.5; done
  rm -rf "/Applications/$APP_NAME.app"
  ditto "$APP" "/Applications/$APP_NAME.app"
  open "/Applications/$APP_NAME.app"
  echo "Installed and opened /Applications/$APP_NAME.app"
fi
