#!/usr/bin/env bash
set -euo pipefail
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt pyinstaller
if ! command -v ffmpeg >/dev/null 2>&1 ; then
  echo "⚠️  ffmpeg not found. Install with: brew install ffmpeg"
fi
pyinstaller app.spec --noconfirm --clean

if [ -f "dist/YT Downloader" ]; then
    rm "dist/YT Downloader"
    echo "Removed duplicate executable (already in .app bundle)"
fi

echo "✅ Built at dist/YT Downloader.app (onedir – rychlý start, bez rozbalování)"
echo "If blocked, allow in Settings → Privacy & Security → Open Anyway."
