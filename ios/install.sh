#!/bin/sh
# Builds NBA Stats for the iPhone and installs it, signed with your Apple Developer team (no 7-day expiry).
# Needs, once: Xcode signed in to your developer account (Settings > Accounts) with an Apple Development certificate,
# and the iPhone connected by cable (trusted, Developer Mode on); after that it can install over Wi-Fi.
# Usage: ios/install.sh            (uses the first connected iPhone and the team in your Apple Development certificate)
#        TEAM=ABCDE12345 ios/install.sh
set -e
cd "$(dirname "$0")"
TEAM="${TEAM:-$(security find-certificate -a -c "Apple Development" -p 2>/dev/null | openssl x509 -noout -subject 2>/dev/null | sed -n 's/.*OU *= *\([A-Z0-9]\{10\}\).*/\1/p' | head -1)}"
[ -n "$TEAM" ] || { echo "No Apple Development certificate found. Sign in to Xcode (Settings > Accounts) and create one first."; exit 1; }
DEVICE="${DEVICE:-$(xcrun devicectl list devices 2>/dev/null | awk '/iPhone/ && !/simulated/ && /(connected|available)/ {for (i = 1; i <= NF; i++) if ($i ~ /^[0-9A-F]{8}-/) {print $i; exit}}')}"
[ -n "$DEVICE" ] || { echo "No iPhone found. Connect it by cable, unlock it and trust this Mac."; exit 1; }
xcodegen generate -q
xcodebuild -project NBAStats.xcodeproj -scheme NBAStats -configuration Release -destination "platform=iOS,id=$DEVICE" \
  -derivedDataPath build -allowProvisioningUpdates DEVELOPMENT_TEAM="$TEAM" CODE_SIGN_STYLE=Automatic \
  CURRENT_PROJECT_VERSION="$(date +%Y%m%d%H%M)" build -quiet
xcrun devicectl device install app --device "$DEVICE" build/Build/Products/Release-iphoneos/NBAStats.app
echo "Installed NBA Stats on your iPhone (team $TEAM)."
