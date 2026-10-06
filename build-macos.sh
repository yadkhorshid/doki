#!/usr/bin/env bash
# Builds doki.app and dist/doki-macOS-<arch>.zip with Chromium, mpv and the Anime4K shaders bundled.
# Usage: ./build-macos.sh [--refresh-mpv]
set -euo pipefail

cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
ANIME4K_URL="https://github.com/bloc97/Anime4K/releases/download/v4.0.1/Anime4K_v4.0.zip"
# Pinned so every release ships the mpv it was tested with; bump both this and build.ps1 together.
MPV_VERSION="v0.41.0"
DOWNLOADS="build/downloads"
SHADERS="mpv/portable_config/shaders"

case "$(uname -m)" in
    arm64) LABEL="arm64"; MPV_BUILD="macos-14-arm" ;;
    x86_64) LABEL="intel"; MPV_BUILD="macos-15-intel" ;;
    *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac
APP="dist/doki.app"
ARCHIVE="dist/doki-macOS-$LABEL.zip"

MPV_URL="https://github.com/mpv-player/mpv/releases/download/$MPV_VERSION/mpv-$MPV_VERSION-$MPV_BUILD.zip"

"$PYTHON" -m pip install -r requirements-build.txt
"$PYTHON" -m playwright install chromium

if [ "${1:-}" = "--refresh-mpv" ]; then
    rm -rf mpv
fi
mkdir -p "$DOWNLOADS" "$SHADERS"

if [ "$(cat mpv/MPV-VERSION.txt 2>/dev/null)" != "$MPV_VERSION" ]; then
    rm -rf mpv/mpv.app
    echo "Downloading mpv $MPV_VERSION ($MPV_BUILD)"
    curl -fsSL -o "$DOWNLOADS/mpv-macos.zip" "$MPV_URL"
    rm -rf "$DOWNLOADS/mpv-macos"
    unzip -q -o "$DOWNLOADS/mpv-macos.zip" -d "$DOWNLOADS/mpv-macos"
    tar -xzf "$DOWNLOADS/mpv-macos/mpv.tar.gz" -C mpv
    cat > mpv/LICENSE-NOTICE.txt <<EOF
This folder contains mpv $MPV_VERSION ($MPV_BUILD) from https://github.com/mpv-player/mpv/releases
and the Anime4K v4.0 shaders (MIT License, https://github.com/bloc97/Anime4K).
mpv is free software licensed under the GPLv2 or later; see https://github.com/mpv-player/mpv
for its license and source code.
EOF
    echo "$MPV_VERSION" > mpv/MPV-VERSION.txt
fi

if [ ! -f "$SHADERS/Anime4K_Clamp_Highlights.glsl" ]; then
    echo "Downloading Anime4K shaders"
    curl -fsSL -o "$DOWNLOADS/Anime4K_v4.0.zip" "$ANIME4K_URL"
    unzip -q -o -j "$DOWNLOADS/Anime4K_v4.0.zip" -d "$SHADERS"
fi
cp assets/mpv-config/mpv.conf mpv/portable_config/mpv.conf
# mpv separates shader paths with ':' on macOS instead of ';'.
sed 's/;~~/:~~/g' assets/mpv-config/input.conf > mpv/portable_config/input.conf

"$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --onedir \
    --name "doki" \
    --osx-bundle-identifier "io.github.yadkhorshid.doki" \
    --add-data "assets:assets" \
    --collect-all playwright \
    --collect-all greenlet \
    --collect-all pyee \
    main.py

RESOURCES="$APP/Contents/Resources"
cp -R mpv "$RESOURCES/mpv"
rm -rf "$RESOURCES/mpv/portable_config/cache" "$RESOURCES/mpv/portable_config/watch_later"

# Bundle the Chromium revision Playwright installed, plus its headless shell.
CHROMIUM_DIR="$("$PYTHON" -c '
import os
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    path = p.chromium.executable_path
while not os.path.basename(path).startswith("chromium-"):
    path = os.path.dirname(path)
print(path)
')"
HEADLESS_DIR="$(dirname "$CHROMIUM_DIR")/$(basename "$CHROMIUM_DIR" | sed 's/^chromium-/chromium_headless_shell-/')"
if [ ! -d "$HEADLESS_DIR" ]; then
    echo "Could not locate the matching Playwright Chromium headless shell." >&2
    exit 1
fi
mkdir -p "$RESOURCES/browsers"
cp -R "$CHROMIUM_DIR" "$HEADLESS_DIR" "$RESOURCES/browsers/"

# Adding files invalidated PyInstaller's ad-hoc signature, so sign the whole bundle again.
codesign --force --deep --sign - "$APP"

rm -f "$ARCHIVE"
ditto -c -k --keepParent "$APP" "$ARCHIVE"
echo "App bundle:  $APP"
echo "Download:    $ARCHIVE"
