#!/usr/bin/env bash
# Install (or replace) the per-user launchd job that runs scripts/run-daily.sh every day at 02:00 local time (JST).
# Usage: scripts/install-launchd.sh [RUN_DIR]     RUN_DIR defaults to ~/snow-hokkaido-run (a clone with the ledger data)
# Remove: launchctl bootout gui/$(id -u)/org.dwg7.snow-hokkaido.daily && rm ~/Library/LaunchAgents/org.dwg7.snow-hokkaido.daily.plist
set -euo pipefail
RUN_DIR="${1:-$HOME/snow-hokkaido-run}"
LABEL=org.dwg7.snow-hokkaido.daily
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$RUN_DIR/logs"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$RUN_DIR/scripts/run-daily.sh</string></array>
  <key>EnvironmentVariables</key><dict><key>SNOW_RUN_DIR</key><string>$RUN_DIR</string></dict>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$RUN_DIR/logs/launchd.out</string>
  <key>StandardErrorPath</key><string>$RUN_DIR/logs/launchd.err</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $PLIST (daily 02:00); run now with: launchctl kickstart gui/$(id -u)/$LABEL"
