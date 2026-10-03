#!/bin/zsh
set -e
cd "$(dirname "$0")"
chmod +x build.sh
./build.sh
osascript -e 'display notification "Build finished" with title "YT Downloader"'
open dist
