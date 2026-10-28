#!/usr/bin/env bash
# Downloads Godot 4 for macOS into tools/godot_mac and extracts Godot.app.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="${GODOT_VERSION:-4.7.2-stable}"
ZIP="Godot_v${VERSION}_macos.universal.zip"
DIR="$REPO/tools/godot_mac"
APP="$DIR/Godot.app"
BIN="$APP/Contents/MacOS/Godot"

if [ -x "$BIN" ]; then
    echo "$BIN"
    exit 0
fi

mkdir -p "$DIR"
echo "Downloading Godot ${VERSION} for macOS into tools/godot_mac..."
curl -fsSL -o "$DIR/$ZIP" "https://github.com/godotengine/godot/releases/download/${VERSION}/${ZIP}"
echo "Extracting ${ZIP}..."
unzip -oq "$DIR/$ZIP" -d "$DIR"
rm -f "$DIR/$ZIP"
chmod +x "$BIN"
xattr -cr "$APP" 2>/dev/null || true
echo "Godot for macOS is ready: $BIN"

