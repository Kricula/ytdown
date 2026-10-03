#!/bin/zsh
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
if ! command -v ffmpeg >/dev/null 2>&1 ; then
  echo "⚠️  ffmpeg not found. Install with: brew install ffmpeg"
fi
python app/main.py
