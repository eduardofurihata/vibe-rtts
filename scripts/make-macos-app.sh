#!/bin/bash
# Build ~/Applications/Vibe RTTS.app: a launcher button for the login agent.
#
# launchd runs the app (the login agent from `make install-mac`), through this
# bundle's compiled launcher: started by LaunchServices (a click), macOS 27 hides
# the menu bar icon of a process owned by a new, unsigned bundle; started by
# launchd it shows it. The launcher staying alive as the app's parent is what
# gives the Microphone permission an owner macOS can ask about. A click on the
# bundle only starts the agent. The code stays in the repo: a git pull updates it.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:-$HOME/Applications/Vibe RTTS.app}"
BUNDLE_ID="com.github.furihata.vibe-rtts"
AGENT_LABEL="com.github.furihata.vibe-rtts"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# Main executable: a compiled launcher that stays alive as the app's parent, so
# the Microphone permission belongs to "Vibe RTTS" (see scripts/macos/launcher.c).
clang -O2 -Wall -DVIBE_RTTS_REPO="\"$REPO\"" \
    -o "$APP/Contents/MacOS/vibe-rtts" "$REPO/scripts/macos/launcher.c"

# What a click does. Already running: a short-lived instance finds it, asks it to
# say so in a notification and exits (app.py) — otherwise a click would seem to do
# nothing. Not running: start the login agent.
cat > "$APP/Contents/Resources/click.sh" <<EOF
#!/bin/bash
if /bin/launchctl print "gui/\$(id -u)/$AGENT_LABEL" 2>/dev/null | grep -q "state = running"; then
    exec "$REPO/scripts/vibe-rtts.sh"
fi
exec /bin/launchctl kickstart "gui/\$(id -u)/$AGENT_LABEL"
EOF
chmod +x "$APP/Contents/Resources/click.sh"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Vibe RTTS</string>
    <key>CFBundleDisplayName</key>
    <string>Vibe RTTS</string>
    <key>CFBundleIdentifier</key>
    <string>$BUNDLE_ID</string>
    <key>CFBundleExecutable</key>
    <string>vibe-rtts</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSMicrophoneUsageDescription</key>
    <string>Vibe RTTS records your voice to transcribe it.</string>
</dict>
</plist>
EOF

# App icon from the "ready" tray icon
ICONSET="$(mktemp -d)/AppIcon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
    sips -z $size $size "$REPO/vibe_rtts/icons/mic-active.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z $double $double "$REPO/vibe_rtts/icons/mic-active.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$(dirname "$ICONSET")"

# Ad-hoc signature: gives the bundle a stable identity for the permission prompts.
codesign --force --sign - "$APP" 2>/dev/null || echo "warning: could not ad-hoc sign $APP"

echo "Built: $APP"
