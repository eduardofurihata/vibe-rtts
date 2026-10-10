#!/bin/bash
# Build ~/Applications/Vibe RTTS.app: a launcher button for the login agent.
#
# The bundle does not run the app itself: it asks launchd to start the agent that
# `make install-mac` installs, which runs scripts/vibe-rtts.sh. macOS 27 hides the
# menu bar icon of a process owned by a new, unsigned bundle — the app would run,
# shortcuts and all, with no icon anywhere — while the same process started by
# launchd shows it. The code stays in the repo, so a git pull updates the app.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:-$HOME/Applications/Vibe RTTS.app}"
BUNDLE_ID="com.github.furihata.vibe-rtts"
AGENT_LABEL="com.github.furihata.vibe-rtts"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/MacOS/vibe-rtts" <<EOF
#!/bin/bash
# Already running: a short-lived instance finds it, asks it to say so in a
# notification and exits (app.py) — otherwise a click would seem to do nothing.
if /bin/launchctl print "gui/\$(id -u)/$AGENT_LABEL" 2>/dev/null | grep -q "state = running"; then
    exec "$REPO/scripts/vibe-rtts.sh"
fi
exec /bin/launchctl kickstart "gui/\$(id -u)/$AGENT_LABEL"
EOF
chmod +x "$APP/Contents/MacOS/vibe-rtts"

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
