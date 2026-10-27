#!/usr/bin/env bash
# Downloads the pinned Godot editor binary into tools/godot and checks it against the official SHA-512.
set -euo pipefail
VERSION="4.7.2-stable"
ZIP="Godot_v${VERSION}_linux.x86_64.zip"
SHA512="9aa00f7a605200940bce3027a567b782f49bd8e940dd06ae9e987bd65aee1b1467edd56ed84fcdcbdd44354bf613bdbb4e5d2913e925850368e150c59ed54c65"
DIR="$(cd "$(dirname "$0")/.." && pwd)/tools/godot"
BIN="$DIR/Godot_v${VERSION}_linux.x86_64"
if [ -x "$BIN" ]; then echo "$BIN"; exit 0; fi
mkdir -p "$DIR"
curl -fsSL -o "$DIR/$ZIP" "https://github.com/godotengine/godot/releases/download/${VERSION}/${ZIP}"
echo "$SHA512  $DIR/$ZIP" | sha512sum -c - >&2
unzip -oq "$DIR/$ZIP" -d "$DIR"
rm "$DIR/$ZIP"
chmod +x "$BIN"
echo "$BIN"
